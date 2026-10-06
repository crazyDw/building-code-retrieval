"""RRF 融合：dense 与 sparse 默认等权，k=60。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

RRF_K = 60


@dataclass(frozen=True, slots=True)
class FusedHit:
    """融合后的块：分数与两路名次。"""

    chunk_id: str
    score: float
    dense_rank: int | None
    sparse_rank: int | None


def rrf_fuse(
    dense_ids: Sequence[str],
    sparse_ids: Sequence[str],
    *,
    k: int = RRF_K,
) -> list[FusedHit]:
    """按 RRF 等权融合两路有序结果，名次从 1 开始。"""
    scores: dict[str, float] = {}
    dense_ranks: dict[str, int] = {}
    sparse_ranks: dict[str, int] = {}
    for rank, chunk_id in enumerate(dense_ids, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
        dense_ranks.setdefault(chunk_id, rank)
    for rank, chunk_id in enumerate(sparse_ids, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
        sparse_ranks.setdefault(chunk_id, rank)
    ordered = sorted(
        scores,
        key=lambda chunk_id: (
            -scores[chunk_id],
            min(
                dense_ranks.get(chunk_id, 10**6),
                sparse_ranks.get(chunk_id, 10**6),
            ),
            chunk_id,
        ),
    )
    return [
        FusedHit(
            chunk_id=chunk_id,
            score=round(scores[chunk_id], 10),
            dense_rank=dense_ranks.get(chunk_id),
            sparse_rank=sparse_ranks.get(chunk_id),
        )
        for chunk_id in ordered
    ]
