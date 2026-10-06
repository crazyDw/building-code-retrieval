"""DEV_MODE 检索退化：SQLite LIKE 关键词模拟。

结果只用于界面与接口联调，不得作为检索质量依据（铁律 20 / D8）。
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable

from archrag.retrieval.context import ContextRequest, build_context
from archrag.retrieval.pipeline import ClauseHit, PipelineConfig, RetrievalResult
from archrag.retrieval.query import plan_query
from archrag.store.sqlite import SqliteStore

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9.]{2,}")


def dev_retrieve(
    question: str,
    *,
    store: SqliteStore,
    config: PipelineConfig,
    count_tokens: Callable[[str], int],
) -> RetrievalResult:
    """用关键词匹配构造 RetrievalResult，保持与正式检索一致的返回结构。"""
    plan = plan_query(
        question,
        alias_index=store.alias_index(),
        expansions=store.query_expansions(),
    )
    terms = _terms(question)
    rows = store.search_chunks_like(terms, limit=max(config.top_n * 3, 30))
    ranked = sorted(rows, key=lambda row: (-_score(row, terms), row["ordinal"]))
    best: dict[str, ClauseHit] = {}
    for row in ranked:
        clause_id = row["clause_id"]
        if not clause_id or clause_id in best:
            continue
        best[clause_id] = ClauseHit(
            clause_id=str(clause_id),
            clause_no=str(row["clause_no"] or ""),
            standard_id=str(row["standard_id"]),
            score=float(_score(row, terms)),
            rrf_score=0.0,
            rerank_score=None,
            matched_kuan=row["kuan_no"],
            matched_chunk_type=str(row["chunk_type"]),
            matched_table_id=row["table_id"] or None,
            matched_row_no=row["row_no"],
            is_reference=False,
        )
        if len(best) >= config.top_n:
            break
    hits = tuple(best.values())
    context = build_context(
        store,
        [
            ContextRequest(
                clause_id=hit.clause_id,
                score=hit.score,
                matched_kuan=hit.matched_kuan,
            )
            for hit in hits
        ],
        count_tokens=count_tokens,
        max_tokens=config.context_max_tokens,
    )
    return RetrievalResult(
        mode="dev_keyword",
        plan=plan,
        hits=hits,
        context=context,
        not_found=not hits,
        degraded=False,
        degraded_reason=None,
        rerank_used=False,
        timings={},
        log_fields={
            "event": "retrieval_dev",
            "question": question,
            "terms": terms,
            "top_clauses": [hit.clause_id for hit in hits],
        },
    )


def _terms(question: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for run in _TOKEN_RE.findall(question):
        if len(run) <= 4:
            tokens.append(run)
        else:
            tokens.extend(run[index : index + 2] for index in range(0, len(run) - 1))
    return tuple(dict.fromkeys(tokens))[:8]


def _score(row: sqlite3.Row, terms: tuple[str, ...]) -> int:
    haystack = f"{row['text']}\n{row['embed_text']}"
    return sum(1 for term in terms if term in haystack)
