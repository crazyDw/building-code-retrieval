"""RRF 融合测试。"""

from __future__ import annotations

from archrag.retrieval.fusion import RRF_K, rrf_fuse


def test_rrf_k_is_60() -> None:
    assert RRF_K == 60


def test_rrf_favours_hits_in_both_lists() -> None:
    fused = rrf_fuse(["a", "b", "c"], ["b", "d"])
    assert fused[0].chunk_id == "b"
    assert fused[0].dense_rank == 2 and fused[0].sparse_rank == 1
    assert [hit.chunk_id for hit in fused[1:]] == ["a", "d", "c"]


def test_rrf_scores_are_deterministic() -> None:
    first = rrf_fuse(["a", "b"], ["b", "a"])
    second = rrf_fuse(["a", "b"], ["b", "a"])
    assert first == second
    assert first[0].score == first[1].score


def test_rrf_handles_empty_lists() -> None:
    assert rrf_fuse([], []) == []
    assert [hit.chunk_id for hit in rrf_fuse([], ["x"])] == ["x"]
