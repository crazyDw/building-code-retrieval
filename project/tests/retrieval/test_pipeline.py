"""检索链路测试：聚合、scope、引用扩展、降级与阈值（假 Milvus/模型）。"""

from __future__ import annotations

import hashlib

import pytest

from archrag.corpus.chunker import build_chunks
from archrag.corpus.models import ChunkType, Standard
from archrag.corpus.parser import parse_text
from archrag.corpus.references import extract_references
from archrag.retrieval.embedder import EmbeddingBatch
from archrag.retrieval.pipeline import PipelineConfig, retrieve
from archrag.store.milvus import MilvusHit
from archrag.store.sqlite import SqliteStore


class FakeEmbedder:
    def __init__(self) -> None:
        self.encode_calls = 0

    def load(self) -> None:
        return None

    def encode(self, texts, **kwargs) -> EmbeddingBatch:
        self.encode_calls += 1
        return EmbeddingBatch(dense=((0.1, 0.2),), sparse=({1: 1.0},))


class FakeMilvus:
    def __init__(self, dense_ids, sparse_ids=None) -> None:
        self.dense_ids = list(dense_ids)
        self.sparse_ids = list(sparse_ids if sparse_ids is not None else dense_ids)
        self.calls: list[tuple[str, int]] = []

    def search_dense(self, vector, *, top_k, standard_id=None):
        self.calls.append(("dense", top_k))
        return [
            MilvusHit(chunk_id=chunk_id, score=1.0 - index * 0.01, fields={})
            for index, chunk_id in enumerate(self.dense_ids[:top_k])
        ]

    def search_sparse(self, sparse, *, top_k, standard_id=None):
        self.calls.append(("sparse", top_k))
        return [
            MilvusHit(chunk_id=chunk_id, score=1.0 - index * 0.01, fields={})
            for index, chunk_id in enumerate(self.sparse_ids[:top_k])
        ]


class FakeReranker:
    def __init__(self, scores) -> None:
        self.scores = list(scores)
        self.calls = 0

    def load(self) -> None:
        return None

    def compute_score(self, pairs, **kwargs):
        self.calls += 1
        return tuple(self.scores[: len(pairs)])


@pytest.fixture()
def store(tmp_path, standard_map, parsed_corpus, chunks_by_standard, corpus_dir):
    sqlite = SqliteStore(tmp_path / "pipeline.sqlite")
    sqlite.initialize()
    for name in ("民用建筑通用规范.md", "住宅项目规范.md"):
        parsed = parsed_corpus[name]
        digest = hashlib.sha256((corpus_dir / name).read_bytes()).hexdigest()
        sqlite.replace_standard(
            parsed,
            chunks_by_standard[name],
            extract_references(parsed),
            source_sha256=digest,
            version=digest[:12],
        )
    return sqlite


def _body_chunk_ids(chunks, limit: int) -> list[str]:
    seen: list[str] = []
    for chunk in chunks:
        if chunk.chunk_type is not ChunkType.BODY or not chunk.clause_id:
            continue
        if chunk.clause_id not in seen:
            seen.append(chunk.chunk_id)
    return seen[:limit]


def _config(**overrides) -> PipelineConfig:
    values = {
        "topk_dense": 30,
        "topk_sparse": 30,
        "rerank_candidates": 25,
        "top_n": 10,
        "rerank_candidates_deep": 40,
        "top_n_deep": 16,
        "ref_expand_limit": 5,
        "score_threshold": 0.0,
        "context_max_tokens": 12000,
        "rerank_enabled": True,
    }
    values.update(overrides)
    return PipelineConfig(**values)


def _run(store, milvus, reranker=None, *, config=None, question="楼梯要求", **kwargs):
    embedder = FakeEmbedder()
    result = retrieve(
        question,
        store=store,
        milvus=milvus,
        embedder=embedder,
        reranker=reranker,
        config=config or _config(),
        count_tokens=lambda text: len(text) // 2,
        **kwargs,
    )
    return result, embedder


def test_aggregation_produces_distinct_clauses(store, chunks_by_standard) -> None:
    ids = _body_chunk_ids(chunks_by_standard["民用建筑通用规范.md"], 25)
    result, _ = _run(store, FakeMilvus(ids), FakeReranker([1.0] * len(ids)))
    assert len(result.hits) == 10
    assert len({hit.clause_id for hit in result.hits}) == 10
    assert result.rerank_used is True


def test_clause_shortcut_skips_models(store) -> None:
    result, embedder = _run(store, FakeMilvus([]), question="5.3.9")
    assert result.mode == "clause_shortcut"
    assert result.hits[0].clause_id == "GB 55031-2022_5.3.9"
    assert embedder.encode_calls == 0
    assert "踏步" in result.context.text


def test_whole_clause_with_tables_is_restored(store, chunks_by_standard) -> None:
    chunks = chunks_by_standard["住宅项目规范.md"]
    table_chunk = next(
        chunk
        for chunk in chunks
        if chunk.chunk_type is ChunkType.TABLE_ROW and chunk.clause_no == "3.1.1"
    )
    result, _ = _run(
        store, FakeMilvus([table_chunk.chunk_id]), FakeReranker([2.0]), question="空间环境控制指标"
    )
    assert result.hits[0].clause_id == "GB 55038-2025_3.1.1"
    assert "表 3.1.1-1" in result.context.text
    assert "居住街坊" in result.context.text


def test_reference_expansion_is_capped_and_not_reranked(store, chunks_by_standard) -> None:
    chunks = chunks_by_standard["民用建筑通用规范.md"]
    source = next(chunk for chunk in chunks if chunk.clause_no == "3.2.6")
    result, _ = _run(
        store,
        FakeMilvus([source.chunk_id]),
        FakeReranker([1.0]),
        question="屋顶设备用房面积要求",
        config=_config(ref_expand_limit=1),
    )
    references = [hit for hit in result.hits if hit.is_reference]
    assert len(references) == 1
    assert references[0].clause_id.startswith("GB 55031-2022_")


def test_disabled_rerank_is_not_degraded(store, chunks_by_standard) -> None:
    ids = _body_chunk_ids(chunks_by_standard["民用建筑通用规范.md"], 5)
    result, _ = _run(store, FakeMilvus(ids), None, config=_config(rerank_enabled=False))
    assert result.rerank_used is False
    assert result.degraded is False
    assert result.not_found is False


def test_gpu_unavailable_degrades_without_threshold(store, chunks_by_standard, monkeypatch) -> None:
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    ids = _body_chunk_ids(chunks_by_standard["民用建筑通用规范.md"], 5)
    result, _ = _run(
        store,
        FakeMilvus(ids),
        FakeReranker([0.0]),
        config=_config(score_threshold=999.0),
    )
    assert result.rerank_used is False
    assert result.degraded is True and result.degraded_reason == "gpu_unavailable"
    assert result.not_found is False


def test_low_rerank_score_marks_not_found(store, chunks_by_standard) -> None:
    ids = _body_chunk_ids(chunks_by_standard["民用建筑通用规范.md"], 3)
    result, _ = _run(
        store,
        FakeMilvus(ids),
        FakeReranker([0.1, 0.05, 0.0]),
        config=_config(score_threshold=0.5),
    )
    assert result.rerank_used is True
    assert result.not_found is True
    assert result.hits


def test_deep_path_uses_deep_parameters(store, chunks_by_standard) -> None:
    ids = _body_chunk_ids(chunks_by_standard["民用建筑通用规范.md"], 50)
    milvus = FakeMilvus(ids)
    result, _ = _run(
        store,
        milvus,
        FakeReranker([1.0] * 40),
        config=_config(rerank_candidates_deep=40, top_n_deep=16),
        deep=True,
    )
    assert ("dense", 30) in milvus.calls
    assert len(result.hits) == 16


def test_numbers_are_logged(store, chunks_by_standard) -> None:
    ids = _body_chunk_ids(chunks_by_standard["民用建筑通用规范.md"], 2)
    result, _ = _run(store, FakeMilvus(ids), FakeReranker([1.0, 0.5]), question="层高3.0m时净高")
    assert result.log_fields["numbers"] == [{"raw": "3.0m", "value": 3.0, "unit": "m"}]
    assert "3.0m" not in result.log_fields["retrieval_text"]


def test_kuan_hit_restores_whole_clause(store, chunks_by_standard, parsed_corpus) -> None:
    kuan_chunk = next(
        chunk
        for chunk in chunks_by_standard["住宅项目规范.md"]
        if chunk.clause_no == "4.2.2" and chunk.kuan_no == 2
    )
    result, _ = _run(
        store, FakeMilvus([kuan_chunk.chunk_id]), FakeReranker([1.0]), question="层高要求"
    )
    assert result.hits[0].clause_id == "GB 55038-2025_4.2.2"
    assert result.hits[0].matched_kuan == 2
    whole_clause = parsed_corpus["住宅项目规范.md"].clause_by_no("4.2.2")
    assert whole_clause.text in result.context.text


def test_scope_does_not_occupy_top_n(tmp_path) -> None:
    standard = Standard(standard_id="GB 55000-2025", name="测试规范", file_name="t.md")
    body = "\n\n".join(f"1.0.{index} 第{index}条要求。" for index in range(1, 13))
    text = (
        f"# 1 总 则\n\n{body}\n\n本规范适用于新建住宅项目。\n"
    )
    parsed = parse_text(text, standard)
    chunks = build_chunks(
        parsed, version="v1", count_tokens=lambda value: len(value) // 2
    )
    sqlite = SqliteStore(tmp_path / "scope.sqlite")
    sqlite.initialize()
    sqlite.replace_standard(
        parsed, chunks, (), source_sha256="e" * 64, version="v1"
    )
    scope_chunk = next(chunk for chunk in chunks if chunk.chunk_type is ChunkType.SCOPE)
    body_chunks = [
        chunk for chunk in chunks if chunk.chunk_type is ChunkType.BODY
    ]
    milvus = FakeMilvus([scope_chunk.chunk_id, *[chunk.chunk_id for chunk in body_chunks]])
    result, _ = _run(
        sqlite,
        milvus,
        FakeReranker([5.0] * (len(body_chunks) + 1)),
        question="防火分区划分要求",
    )
    assert len(result.hits) == 10
    assert len({hit.clause_id for hit in result.hits}) == 10
    assert all(hit.matched_chunk_type != "scope" for hit in result.hits)
    assert result.context.scope_qualifiers == ("本规范适用于新建住宅项目。",)
