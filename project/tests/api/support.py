"""API 测试共用夹具与假外部依赖（Milvus / 模型 / 生成客户端）。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from archrag.api.app import create_app
from archrag.api.deps import AppState
from archrag.config import load_settings
from archrag.corpus.references import extract_references
from archrag.generation.client import StreamPiece
from archrag.retrieval.embedder import EmbeddingBatch
from archrag.store.milvus import MilvusHit
from archrag.store.sqlite import SqliteStore

CLAUSE_ID = "GB 55031-2022_5.3.9"

VALID = (
    "<!--推导-->\n"
    "按条文，楼梯踏步在离内侧扶手中心 0.25m 处宽度不应小于 0.22m。"
    f"[[clause:{CLAUSE_ID}]]\n"
    "<!--原文-->\n"
    "5.3.9 公共楼梯踏步的最小宽度和最大高度应符合表 5.3.9 的规定。"
    "螺旋楼梯和扇形踏步离内侧扶手中心 0.25m 处的踏步宽度不应小于 0.22m。"
    f"[[clause:{CLAUSE_ID}]]"
)

TAMPERED = (
    "<!--推导-->\n"
    f"按条文取值。[[clause:{CLAUSE_ID}]]\n"
    "<!--原文-->\n"
    "螺旋楼梯和扇形踏步离内侧扶手中心 0.25m 处的踏步宽度不应小于 0.30m。"
    f"[[clause:{CLAUSE_ID}]]"
)


class FakeMilvus:
    """可配置检索结果的假 Milvus；同时可当重建目标。"""

    def __init__(self, dense_ids=(), sparse_ids=None) -> None:
        self.dense_ids = list(dense_ids)
        self.sparse_ids = list(sparse_ids if sparse_ids is not None else dense_ids)
        self.calls: list[str] = []
        self.counts: dict[str, int] = {}

    def is_available(self) -> bool:
        return True

    def ensure_collection(self, *, drop_existing: bool = False) -> None:
        self.calls.append("ensure_collection")
        if drop_existing:
            self.counts = {}

    def drop(self) -> None:
        self.calls.append("drop")

    def delete_standard(self, standard_id: str) -> None:
        self.calls.append(f"delete:{standard_id}")
        self.counts.pop(standard_id, None)

    def insert_chunks(self, vectors) -> int:
        self.calls.append("insert")
        for vector in vectors:
            self.counts[vector.standard_id] = self.counts.get(vector.standard_id, 0) + 1
        return len(vectors)

    def flush(self) -> None:
        self.calls.append("flush")

    def count(self, standard_id: str | None = None) -> int:
        if standard_id is None:
            return sum(self.counts.values())
        return self.counts.get(standard_id, 0)

    def search_dense(self, vector, *, top_k, standard_id=None):
        self.calls.append("search_dense")
        return [
            MilvusHit(chunk_id=chunk_id, score=1.0 - index * 0.01, fields={})
            for index, chunk_id in enumerate(self.dense_ids[:top_k])
        ]

    def search_sparse(self, sparse, *, top_k, standard_id=None):
        self.calls.append("search_sparse")
        return [
            MilvusHit(chunk_id=chunk_id, score=1.0 - index * 0.01, fields={})
            for index, chunk_id in enumerate(self.sparse_ids[:top_k])
        ]


class FakeEmbedder:
    is_loaded = True

    def load(self) -> None:
        return None

    def encode(self, texts, **kwargs) -> EmbeddingBatch:
        return EmbeddingBatch(
            dense=tuple((0.1, 0.2) for _ in texts),
            sparse=tuple({1: 1.0} for _ in texts),
        )


class FakeReranker:
    is_loaded = True

    def load(self) -> None:
        return None

    def compute_score(self, pairs, **kwargs):
        return tuple(10.0 for _ in pairs)


class FakeClient:
    """脚本化生成客户端；记录调用次数与 thinking 开关。"""

    def __init__(self, answers, *, reasoning=(), error=None) -> None:
        self._answers = list(answers)
        self._reasoning = list(reasoning)
        self._error = error
        self.calls: list[dict] = []

    def stream(self, system, user, *, thinking=False):
        self.calls.append({"thinking": thinking, "user": user})
        if self._error is not None:
            raise self._error
        answer = self._answers.pop(0)
        for piece in self._reasoning:
            yield StreamPiece("reasoning", piece)
        for start in range(0, len(answer), 20):
            yield StreamPiece("content", answer[start : start + 20])


class FakeTokenCounter:
    def count(self, text: str) -> int:
        return max(1, len(text) // 2)


def build_store(
    tmp_path: Path,
    parsed_corpus,
    chunks_by_standard,
    corpus_dir: Path,
    names=("民用建筑通用规范.md", "住宅项目规范.md", "混凝土结构通用规范.md"),
) -> SqliteStore:
    store = SqliteStore(tmp_path / "api.sqlite")
    store.initialize()
    for name in names:
        parsed = parsed_corpus[name]
        digest = hashlib.sha256((corpus_dir / name).read_bytes()).hexdigest()
        store.replace_standard(
            parsed,
            chunks_by_standard[name],
            extract_references(parsed),
            source_sha256=digest,
            version=digest[:12],
        )
    return store


def body_chunk_id(chunks_by_standard, file_name: str, clause_no: str) -> str:
    return next(
        chunk.chunk_id
        for chunk in chunks_by_standard[file_name]
        if chunk.clause_no == clause_no and chunk.chunk_type.value == "body"
    )


def table_chunk_id(chunks_by_standard, file_name: str, clause_no: str) -> str:
    return next(
        chunk.chunk_id
        for chunk in chunks_by_standard[file_name]
        if chunk.clause_no == clause_no and chunk.chunk_type.value == "table_row"
    )


def build_settings(tmp_path: Path, *, dev_mode: bool = False):
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "\n".join(
            [
                "DEEPSEEK_API_KEY=sk-test",
                "BASE_URL=https://api.deepseek.com",
                "MODEL=deepseek-flash",
                "EMBED_MODEL=missing-model",
                "RERANK_MODEL=missing-reranker",
                "MILVUS_URI=http://127.0.0.1:1",
                "MILVUS_COLLECTION=arch_regulations_test",
                f"SQLITE_PATH={tmp_path / 'api.sqlite'}",
                f"STANDARD_MAP_PATH={tmp_path / 'map.md'}",
                "SCORE_THRESHOLD=0.0",
                f"DEV_MODE={'true' if dev_mode else 'false'}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return load_settings(env_file=env_file, environ={})


def build_app(settings, store, milvus=None, client=None, *, warmup: bool = False):
    state = AppState(
        settings=settings,
        store=store,
        milvus=milvus or FakeMilvus(),
        embedder=FakeEmbedder(),
        reranker=FakeReranker(),
        client=client or FakeClient([VALID]),
        token_counter=FakeTokenCounter(),
    )
    return create_app(settings=settings, services=state, warmup=warmup), state


def parse_sse(lines) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    current = ""
    for line in lines:
        if line.startswith("event: "):
            current = line[len("event: ") :]
        elif line.startswith("data: "):
            events.append((current, json.loads(line[len("data: ") :])))
    return events
