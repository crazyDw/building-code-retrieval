"""检索链路：查询理解 → 双路召回 → RRF → 重排 → 按条聚合 → 引用扩展 → 上下文。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from archrag.config import Settings
from archrag.retrieval.context import ContextRequest, ContextResult, build_context
from archrag.retrieval.embedder import BgeM3Embedder
from archrag.retrieval.fusion import FusedHit, rrf_fuse
from archrag.retrieval.query import QueryPlan, plan_query
from archrag.retrieval.reranker import BgeReranker
from archrag.store.milvus import MilvusStore
from archrag.store.sqlite import SqliteStore


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """检索参数快照；默认路径与深度路径分别取值。"""

    topk_dense: int = 30
    topk_sparse: int = 30
    rerank_candidates: int = 25
    top_n: int = 10
    rerank_candidates_deep: int = 40
    top_n_deep: int = 16
    ref_expand_limit: int = 5
    score_threshold: float = 0.0
    context_max_tokens: int = 12000
    rerank_enabled: bool = True

    @classmethod
    def from_settings(cls, settings: Settings) -> PipelineConfig:
        return cls(
            topk_dense=settings.topk_dense,
            topk_sparse=settings.topk_sparse,
            rerank_candidates=settings.rerank_candidates,
            top_n=settings.top_n_default,
            rerank_candidates_deep=settings.rerank_candidates_deep,
            top_n_deep=settings.top_n_deep,
            ref_expand_limit=settings.ref_expand_limit,
            score_threshold=settings.score_threshold,
            context_max_tokens=settings.context_max_tokens,
            rerank_enabled=settings.rerank_enabled,
        )


@dataclass(frozen=True, slots=True)
class ClauseHit:
    """聚合到「条」的命中；chunk 信息用于表格高亮与款定位。"""

    clause_id: str
    clause_no: str
    standard_id: str
    score: float
    rrf_score: float
    rerank_score: float | None
    matched_kuan: int | None
    matched_chunk_type: str
    matched_table_id: str | None
    matched_row_no: int | None
    is_reference: bool


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """一轮检索的完整结果与日志字段。"""

    mode: str
    plan: QueryPlan
    hits: tuple[ClauseHit, ...]
    context: ContextResult
    not_found: bool
    degraded: bool
    degraded_reason: str | None
    rerank_used: bool
    timings: dict[str, float]
    log_fields: dict[str, Any]


def retrieve(
    question: str,
    *,
    store: SqliteStore,
    milvus: MilvusStore,
    embedder: BgeM3Embedder,
    config: PipelineConfig,
    reranker: BgeReranker | None = None,
    deep: bool = False,
    rewriter: Callable[[str], str] | None = None,
    logger: logging.Logger | None = None,
    count_tokens: Callable[[str], int],
) -> RetrievalResult:
    """执行一轮检索；条款号命中时短路，不调用模型。"""
    started = time.monotonic()
    plan = plan_query(
        question,
        alias_index=store.alias_index(),
        expansions=store.query_expansions(),
        rewriter=rewriter,
    )
    if plan.clause_no is not None:
        return _clause_shortcut(
            plan,
            store=store,
            config=config,
            count_tokens=count_tokens,
            started=started,
            logger=logger,
        )

    candidates_count = (
        config.rerank_candidates_deep if deep else config.rerank_candidates
    )
    top_n = config.top_n_deep if deep else config.top_n
    timings: dict[str, float] = {}

    embed_started = time.monotonic()
    embedder.load()
    encoding = embedder.encode([plan.retrieval_text])
    timings["embed_ms"] = _ms(embed_started)

    scope: str | Sequence[str] | None = plan.standard_scope or None
    search_started = time.monotonic()
    dense_hits = milvus.search_dense(
        encoding.dense[0], top_k=config.topk_dense, standard_id=scope
    )
    sparse_hits = milvus.search_sparse(
        encoding.sparse[0], top_k=config.topk_sparse, standard_id=scope
    )
    timings["search_ms"] = _ms(search_started)

    fusion_started = time.monotonic()
    fused = rrf_fuse(
        [hit.chunk_id for hit in dense_hits],
        [hit.chunk_id for hit in sparse_hits],
    )[:candidates_count]
    timings["fusion_ms"] = _ms(fusion_started)

    rows = {
        row["chunk_id"]: row for row in store.chunks_by_ids([hit.chunk_id for hit in fused])
    }
    ranked, rerank_used, degraded, degraded_reason, rerank_ms = _rank_candidates(
        fused, rows, plan, config, reranker
    )
    timings["rerank_ms"] = rerank_ms

    not_found = bool(
        rerank_used
        and ranked
        and (ranked[0][1] or 0.0) < config.score_threshold
    )
    hits = _aggregate(ranked, top_n=top_n)
    hits = _expand_references(hits, store=store, limit=config.ref_expand_limit)

    context_started = time.monotonic()
    context = build_context(
        store,
        [
            ContextRequest(
                clause_id=hit.clause_id,
                score=hit.rerank_score if hit.rerank_score is not None else hit.score,
                matched_kuan=hit.matched_kuan,
                is_reference=hit.is_reference,
            )
            for hit in hits
        ],
        count_tokens=count_tokens,
        max_tokens=config.context_max_tokens,
    )
    timings["context_ms"] = _ms(context_started)
    timings["total_ms"] = _ms(started)

    log_fields = _log_fields(
        question=question,
        plan=plan,
        ranked=ranked,
        hits=hits,
        not_found=not_found,
        degraded=degraded,
        degraded_reason=degraded_reason,
        rerank_used=rerank_used,
        timings=timings,
    )
    if logger is not None:
        logger.info("检索完成：%s", question, extra=log_fields)
    return RetrievalResult(
        mode="search",
        plan=plan,
        hits=hits,
        context=context,
        not_found=not_found,
        degraded=degraded,
        degraded_reason=degraded_reason,
        rerank_used=rerank_used,
        timings=timings,
        log_fields=log_fields,
    )


def _clause_shortcut(
    plan: QueryPlan,
    *,
    store: SqliteStore,
    config: PipelineConfig,
    count_tokens: Callable[[str], int],
    started: float,
    logger: logging.Logger | None,
) -> RetrievalResult:
    clause_ids = store.clause_ids_by_no(
        plan.clause_no or "", standard_id=plan.clause_standard_id
    )
    context = build_context(
        store,
        [ContextRequest(clause_id=clause_id, score=1.0) for clause_id in clause_ids],
        count_tokens=count_tokens,
        max_tokens=config.context_max_tokens,
    )
    hits = tuple(
        ClauseHit(
            clause_id=clause_id,
            clause_no=plan.clause_no or "",
            standard_id=clause_id.rsplit("_", 1)[0],
            score=1.0,
            rrf_score=1.0,
            rerank_score=None,
            matched_kuan=None,
            matched_chunk_type="body",
            matched_table_id=None,
            matched_row_no=None,
            is_reference=False,
        )
        for clause_id in clause_ids
    )
    timings = {"total_ms": _ms(started)}
    log_fields = _log_fields(
        question=plan.original,
        plan=plan,
        ranked=[],
        hits=hits,
        not_found=not clause_ids,
        degraded=False,
        degraded_reason=None,
        rerank_used=False,
        timings=timings,
    )
    if logger is not None:
        logger.info("条款号直查：%s", plan.clause_no, extra=log_fields)
    return RetrievalResult(
        mode="clause_shortcut",
        plan=plan,
        hits=hits,
        context=context,
        not_found=not clause_ids,
        degraded=False,
        degraded_reason=None,
        rerank_used=False,
        timings=timings,
        log_fields=log_fields,
    )


def _rank_candidates(
    fused: Sequence[FusedHit],
    rows: dict[str, Any],
    plan: QueryPlan,
    config: PipelineConfig,
    reranker: BgeReranker | None,
) -> tuple[list[tuple[FusedHit, float | None, Any]], bool, bool, str | None, float]:
    available = [hit for hit in fused if hit.chunk_id in rows]
    if not config.rerank_enabled:
        return [(hit, None, rows[hit.chunk_id]) for hit in available], False, False, None, 0.0
    import torch

    if not torch.cuda.is_available():
        return (
            [(hit, None, rows[hit.chunk_id]) for hit in available],
            False,
            True,
            "gpu_unavailable",
            0.0,
        )
    if reranker is None:
        return (
            [(hit, None, rows[hit.chunk_id]) for hit in available],
            False,
            True,
            "reranker_unavailable",
            0.0,
        )
    rerank_started = time.monotonic()
    try:
        reranker.load()
        pairs = [
            (plan.retrieval_text, str(rows[hit.chunk_id]["embed_text"]))
            for hit in available
        ]
        scores = reranker.compute_score(pairs)
        ranked: list[tuple[FusedHit, float | None, Any]] = sorted(
            (
                (hit, score, rows[hit.chunk_id])
                for hit, score in zip(available, scores, strict=True)
            ),
            key=lambda item: (-(item[1] or 0.0), -item[0].score, item[0].chunk_id),
        )
        return ranked, True, False, None, _ms(rerank_started)
    except Exception:
        return (
            [(hit, None, rows[hit.chunk_id]) for hit in available],
            False,
            True,
            "rerank_failed",
            _ms(rerank_started),
        )


def _aggregate(
    ranked: Sequence[tuple[FusedHit, float | None, Any]], *, top_n: int
) -> tuple[ClauseHit, ...]:
    best: dict[str, ClauseHit] = {}
    for fused, rerank_score, row in ranked:
        if row["chunk_type"] == "scope":
            continue
        clause_id = row["clause_id"]
        if not clause_id or clause_id in best:
            continue
        best[clause_id] = ClauseHit(
            clause_id=str(clause_id),
            clause_no=str(row["clause_no"] or ""),
            standard_id=str(row["standard_id"]),
            score=float(rerank_score if rerank_score is not None else fused.score),
            rrf_score=fused.score,
            rerank_score=rerank_score,
            matched_kuan=row["kuan_no"],
            matched_chunk_type=str(row["chunk_type"]),
            matched_table_id=row["table_id"] or None,
            matched_row_no=row["row_no"],
            is_reference=False,
        )
        if len(best) >= top_n:
            break
    return tuple(best.values())


def _expand_references(
    hits: Sequence[ClauseHit], *, store: SqliteStore, limit: int
) -> tuple[ClauseHit, ...]:
    known = {hit.clause_id for hit in hits}
    targets: list[str] = []
    for row in store.clause_reference_targets([hit.clause_id for hit in hits]):
        target = str(row["dst_id"])
        if target and target not in known and target not in targets:
            targets.append(target)
    if not targets:
        return tuple(hits)
    existing = {row["clause_id"] for row in store.clauses_by_ids(targets[:limit])}
    expanded = list(hits)
    for target in targets:
        if len(expanded) - len(hits) >= limit:
            break
        if target not in existing:
            continue
        expanded.append(
            ClauseHit(
                clause_id=target,
                clause_no=target.rsplit("_", 1)[-1],
                standard_id=target.rsplit("_", 1)[0],
                score=0.0,
                rrf_score=0.0,
                rerank_score=None,
                matched_kuan=None,
                matched_chunk_type="body",
                matched_table_id=None,
                matched_row_no=None,
                is_reference=True,
            )
        )
    return tuple(expanded)


def _log_fields(
    *,
    question: str,
    plan: QueryPlan,
    ranked: Sequence[tuple[FusedHit, float | None, Any]],
    hits: Sequence[ClauseHit],
    not_found: bool,
    degraded: bool,
    degraded_reason: str | None,
    rerank_used: bool,
    timings: dict[str, float],
) -> dict[str, Any]:
    return {
        "event": "retrieval",
        "question": question,
        "retrieval_text": plan.retrieval_text,
        "clause_no": plan.clause_no,
        "standard_scope": list(plan.standard_scope),
        "numbers": [
            {"raw": number.raw, "value": number.value, "unit": number.unit}
            for number in plan.numbers
        ],
        "expanded_terms": list(plan.expanded_terms),
        "broad": plan.is_broad,
        "rewrite_needed": plan.rewrite_needed,
        "rewrite_used": plan.rewrite_used,
        "candidates": [
            {
                "chunk_id": fused.chunk_id,
                "rrf_score": fused.score,
                "rerank_score": rerank_score,
            }
            for fused, rerank_score, _ in ranked
        ],
        "top_clauses": [hit.clause_id for hit in hits],
        "not_found": not_found,
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "rerank_used": rerank_used,
        "timings": timings,
    }


def _ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 2)
