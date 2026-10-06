"""从 SQLite 重建 Milvus：可全量或按标准执行，可重复且结果一致。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from archrag.errors import ReindexError, StoreError
from archrag.retrieval.embedder import BgeM3Embedder
from archrag.store.milvus import ChunkVector, MilvusStore
from archrag.store.sqlite import SqliteStore


@dataclass(frozen=True, slots=True)
class ReindexReport:
    """重建结果：分标准实体数、嵌入块数与批次数。"""

    counts: dict[str, int]
    embedded: int
    batches: int


def reindex(
    store: SqliteStore,
    milvus: MilvusStore,
    embedder: BgeM3Embedder,
    *,
    standard_ids: Sequence[str] | None = None,
    batch_size: int = 32,
    drop_all: bool = True,
    dev_mode: bool = False,
) -> ReindexReport:
    """drop + create（或按标准删除）+ 从 SQLite 全量重嵌入、重写入。"""
    if dev_mode:
        return ReindexReport(counts={}, embedded=0, batches=0)
    rows = store.chunks_for_reindex(standard_ids)
    if not rows:
        raise ReindexError("SQLite 中没有可重建的块")
    expected = store.chunk_counts_by_standard()
    selected = list(standard_ids) if standard_ids else sorted(expected)
    expected = {standard_id: expected[standard_id] for standard_id in selected}

    drop_existing = drop_all and standard_ids is None
    milvus.ensure_collection(drop_existing=drop_existing)
    if standard_ids is not None:
        for standard_id in standard_ids:
            milvus.delete_standard(standard_id)

    embedder.load()
    embedded = 0
    batches = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        encoding = embedder.encode([str(row["embed_text"]) for row in batch])
        vectors = [
            ChunkVector(
                chunk_id=str(row["chunk_id"]),
                standard_id=str(row["standard_id"]),
                level=str(row["level"]),
                chunk_type=str(row["chunk_type"]),
                clause_id=row["clause_id"],
                section_id=row["section_id"],
                clause_no=row["clause_no"],
                kuan_no=row["kuan_no"],
                table_id=row["table_id"],
                row_no=row["row_no"],
                dense=encoding.dense[index],
                sparse=encoding.sparse[index],
            )
            for index, row in enumerate(batch)
        ]
        milvus.insert_chunks(vectors)
        embedded += len(vectors)
        batches += 1

    milvus.flush()
    counts = {standard_id: milvus.count(standard_id) for standard_id in selected}
    if counts != expected:
        raise ReindexError(f"实体数核对失败：Milvus {counts}，SQLite {expected}")
    if embedded != sum(expected.values()):
        raise StoreError(f"嵌入块数 {embedded} 与 SQLite {sum(expected.values())} 不一致")
    return ReindexReport(counts=counts, embedded=embedded, batches=batches)
