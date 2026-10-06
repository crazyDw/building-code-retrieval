"""全量重建：SQLite → 重嵌入 → Milvus，实体数核对与检索冒烟。"""

from __future__ import annotations

import hashlib

import pytest

from archrag.retrieval.reindex import reindex
from archrag.store.sqlite import SqliteStore

pytestmark = [pytest.mark.milvus, pytest.mark.gpu]


def _build_sqlite(tmp_path, standard_map, parsed_corpus, chunks_by_standard, corpus_dir):
    store = SqliteStore(tmp_path / "reindex.sqlite")
    store.initialize()
    for name, parsed in parsed_corpus.items():
        digest = hashlib.sha256((corpus_dir / name).read_bytes()).hexdigest()
        store.replace_standard(
            parsed,
            chunks_by_standard[name],
            (),
            source_sha256=digest,
            version=digest[:12],
        )
    return store


def test_full_reindex_matches_sqlite(
    tmp_path,
    standard_map,
    parsed_corpus,
    chunks_by_standard,
    corpus_dir,
    embedder,
    milvus_factory,
) -> None:
    sqlite_store = _build_sqlite(
        tmp_path, standard_map, parsed_corpus, chunks_by_standard, corpus_dir
    )
    expected = sqlite_store.chunk_counts_by_standard()
    milvus = milvus_factory("archrag_test_reindex")
    try:
        report = reindex(sqlite_store, milvus, embedder, batch_size=32)
        assert report.counts == expected
        assert report.embedded == sum(expected.values()) == 701
        query = embedder.encode(["楼梯踏步的最小宽度和最大高度"]).dense[0]
        hits = milvus.search_dense(query, top_k=5)
        clause_ids = {hit.fields.get("clause_id") for hit in hits}
        assert "GB 55031-2022_5.3.9" in clause_ids
        sparse_hits = milvus.search_sparse(
            embedder.encode(["楼梯踏步"]).sparse[0], top_k=5
        )
        assert sparse_hits
        again = reindex(sqlite_store, milvus, embedder, batch_size=32)
        assert again.counts == expected
    finally:
        milvus.drop()
