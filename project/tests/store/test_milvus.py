"""Milvus schema、写入、两路检索与按标准删除测试（假向量，无需 GPU）。"""

from __future__ import annotations

import pytest

from archrag.store.milvus import ChunkVector, MilvusStore

pytestmark = pytest.mark.milvus

_DIM = 1024


def _dense(index: int) -> tuple[float, ...]:
    vector = [0.0] * _DIM
    vector[index] = 1.0
    return tuple(vector)


def _sample_vectors() -> list[ChunkVector]:
    return [
        ChunkVector(
            "A1",
            "GB-A",
            "全文强制",
            "body",
            "GB-A_1.0.1",
            "1",
            "1.0.1",
            None,
            None,
            None,
            _dense(0),
            {10: 0.9, 11: 0.5},
        ),
        ChunkVector(
            "A2",
            "GB-A",
            "全文强制",
            "table_row",
            "GB-A_1.0.2",
            "1",
            "1.0.2",
            None,
            "表 1.0.2",
            2,
            _dense(1),
            {20: 0.8},
        ),
        ChunkVector(
            "B1",
            "GB-B",
            "全文强制",
            "body",
            "GB-B_2.0.1",
            "2",
            "2.0.1",
            1,
            None,
            None,
            _dense(2),
            {10: 0.4},
        ),
    ]


def test_schema_has_no_text_fields(milvus_store: MilvusStore) -> None:
    fields = {
        field["name"]
        for field in milvus_store._get_client()
        .describe_collection(milvus_store.collection)["fields"]
    }
    assert "dense" in fields and "sparse" in fields
    assert not {"text", "embed_text"} & fields
    assert {"standard_id", "level", "chunk_type", "clause_id", "section_id"} <= fields


def test_insert_count_and_filter(milvus_store: MilvusStore) -> None:
    assert milvus_store.insert_chunks(_sample_vectors()) == 3
    milvus_store.flush()
    assert milvus_store.count() == 3
    assert milvus_store.count("GB-A") == 2
    assert milvus_store.count("GB-B") == 1


def test_dense_search_and_standard_filter(milvus_store: MilvusStore) -> None:
    milvus_store.insert_chunks(_sample_vectors())
    milvus_store.flush()
    hits = milvus_store.search_dense(_dense(0), top_k=3)
    assert hits[0].chunk_id == "A1"
    assert hits[0].score == pytest.approx(1.0, abs=1e-3)
    filtered = milvus_store.search_dense(_dense(0), top_k=3, standard_id="GB-B")
    assert [hit.chunk_id for hit in filtered] == ["B1"]
    assert filtered[0].fields["standard_id"] == "GB-B"


def test_sparse_search(milvus_store: MilvusStore) -> None:
    milvus_store.insert_chunks(_sample_vectors())
    milvus_store.flush()
    hits = milvus_store.search_sparse({10: 1.0}, top_k=3)
    assert [hit.chunk_id for hit in hits] == ["A1", "B1"]
    assert hits[0].score == pytest.approx(0.9, abs=1e-3)


def test_delete_standard(milvus_store: MilvusStore) -> None:
    milvus_store.insert_chunks(_sample_vectors())
    milvus_store.flush()
    milvus_store.delete_standard("GB-A")
    assert milvus_store.count() == 1
    assert milvus_store.count("GB-A") == 0
    assert milvus_store.count("GB-B") == 1
