"""问答接口：SSE 流式（meta / reasoning / answer / reset / error / done）。"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import AsyncIterator, Generator, Iterator

import anyio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from archrag.api.catalog import _table_payloads
from archrag.api.deps import AppState, ReadyDep
from archrag.api.schemas import ChatRequest
from archrag.generation.service import (
    GenerationResult,
    ProjectCondition,
    stream_answer,
)
from archrag.retrieval.dev_search import dev_retrieve
from archrag.retrieval.pipeline import PipelineConfig, RetrievalResult, retrieve

router = APIRouter()
logger = logging.getLogger("archrag.retrieval")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _next_or_none(iterator: Iterator[str]) -> str | None:
    try:
        return next(iterator)
    except StopIteration:
        return None


@router.post("/api/chat")
async def chat(payload: ChatRequest, request: Request, state: ReadyDep) -> StreamingResponse:
    iterator = _event_iterator(payload, state)

    async def event_stream() -> AsyncIterator[str]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                chunk = await anyio.to_thread.run_sync(_next_or_none, iterator)
                if chunk is None:
                    break
                yield chunk
        finally:
            iterator.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _event_iterator(payload: ChatRequest, state: AppState) -> Generator[str, None, None]:
    """同步事件生成器；客户端断开时由外层关闭以停止消费模型流。"""
    try:
        retrieval = _retrieve(payload, state)
    except Exception as exc:
        yield _sse("error", {"code": "retrieval_failed", "message": type(exc).__name__})
        yield _sse("done", _done_payload(state, None, None, error=True))
        return

    if retrieval.mode == "clause_shortcut":
        yield _sse("meta", _meta_payload(state, retrieval))
        yield _sse(
            "answer",
            {"block": "original", "delta": retrieval.context.text},
        )
        yield _sse("done", _done_payload(state, retrieval, None))
        return

    conditions = [
        ProjectCondition(
            key=item.key,
            label=item.label or item.key,
            value=item.value,
            source="user",
            locked=item.locked,
        )
        for item in payload.project_conditions
    ]
    try:
        for event in stream_answer(
            payload.message,
            retrieval=retrieval,
            client=state.client,
            store=state.store,
            count_tokens=state.token_counter.count,
            project_conditions=conditions,
            referenced_clause_ids=payload.referenced_clause_ids,
            deep=payload.deep_analysis,
        ):
            if event.kind == "meta":
                yield _sse("meta", {**_meta_payload(state, retrieval), **event.data})
            elif event.kind == "reasoning":
                yield _sse("reasoning", {"delta": event.data})
            elif event.kind == "derivation":
                yield _sse("answer", {"block": "derivation", "delta": event.data})
            elif event.kind == "reset":
                yield _sse("reset", event.data)
            elif event.kind == "original":
                yield _sse("answer", {"block": "original", "delta": event.data})
            elif event.kind == "done":
                yield _sse("done", _done_payload(state, retrieval, event.data))
    except Exception as exc:
        yield _sse("error", {"code": "generation_failed", "message": type(exc).__name__})
        yield _sse("done", _done_payload(state, retrieval, None, error=True))


def _retrieve(payload: ChatRequest, state: AppState) -> RetrievalResult:
    config = PipelineConfig.from_settings(state.settings)
    count_tokens = state.token_counter.count
    if state.settings.dev_mode:
        result = dev_retrieve(
            payload.message, store=state.store, config=config, count_tokens=count_tokens
        )
        logger.info("检索完成：%s", payload.message, extra=result.log_fields)
        return result
    return retrieve(
        payload.message,
        store=state.store,
        milvus=state.milvus,
        embedder=state.embedder,
        reranker=state.reranker,
        config=config,
        deep=payload.deep_analysis,
        count_tokens=count_tokens,
        logger=logger,
    )


def _meta_payload(state: AppState, retrieval: RetrievalResult) -> dict:
    return {
        "mode": retrieval.mode,
        "dev_mode": state.settings.dev_mode,
        "not_found": retrieval.not_found,
        "broad": retrieval.plan.is_broad,
        "rerank_used": retrieval.rerank_used,
        "degraded_flag": retrieval.degraded,
        "degraded_reason": retrieval.degraded_reason,
        "numbers": [number.raw for number in retrieval.plan.numbers],
    }


def _done_payload(
    state: AppState,
    retrieval: RetrievalResult | None,
    result: GenerationResult | None,
    *,
    error: bool = False,
) -> dict:
    citations: list[dict] = []
    tables: list[dict] = []
    section_hint = None
    if retrieval is not None:
        contexts = {clause.clause_id: clause for clause in retrieval.context.clauses}
        for hit in retrieval.hits:
            context = contexts.get(hit.clause_id)
            clause_row = state.store.clause_row(hit.clause_id)
            citations.append(
                {
                    "clause_id": hit.clause_id,
                    "clause_no": hit.clause_no,
                    "standard_id": hit.standard_id,
                    "standard_name": context.standard_name if context else hit.standard_id,
                    "path": list(context.path) if context else [],
                    "chapter_no": int(clause_row["chapter_no"]) if clause_row else None,
                    "section_id": context.section_id if context else None,
                    "matched_kuan": hit.matched_kuan,
                    "is_reference": hit.is_reference,
                }
            )
            if context is None:
                continue
            for table in _table_payloads(state.store, hit.standard_id, hit.clause_no):
                highlight = []
                if table["table_id"] == (hit.matched_table_id or ""):
                    highlight = [hit.matched_row_no] if hit.matched_row_no else []
                tables.append({**table, "clause_id": hit.clause_id, "highlight_rows": highlight})
        if retrieval.hits:
            first = contexts.get(retrieval.hits[0].clause_id)
            if first is not None:
                listed = sum(
                    1
                    for hit in retrieval.hits
                    if contexts.get(hit.clause_id) is not None
                    and contexts[hit.clause_id].section_id == first.section_id
                )
                section_hint = {
                    "section_id": first.section_id,
                    "section_clause_count": first.section_clause_count,
                    "listed_count": listed,
                }
    if result is not None:
        flags = {
            "fallback_flag": result.fallback_flag,
            "degraded_flag": result.degraded_flag,
            "degraded_reason": result.degraded_reason,
            "rerank_used": result.rerank_used,
            "not_found": result.not_found,
            "broad": result.broad,
            "superseded_notice": result.superseded_notice,
            "project_conditions": [
                dataclasses.asdict(condition) for condition in result.project_conditions
            ],
            "numbers": list(result.numbers),
            "attempts": result.attempts,
            "timings": result.timings,
        }
    else:
        flags = {
            "fallback_flag": error,
            "degraded_flag": retrieval.degraded if retrieval else False,
            "degraded_reason": retrieval.degraded_reason if retrieval else None,
            "rerank_used": retrieval.rerank_used if retrieval else False,
            "not_found": retrieval.not_found if retrieval else True,
            "broad": retrieval.plan.is_broad if retrieval else False,
            "superseded_notice": None,
            "project_conditions": [],
            "numbers": [],
            "attempts": 0,
            "timings": {},
        }
    return {
        "citations": citations,
        "tables": tables,
        "section_hint": section_hint,
        "mode": retrieval.mode if retrieval else "error",
        "dev_mode": state.settings.dev_mode,
        **flags,
    }
