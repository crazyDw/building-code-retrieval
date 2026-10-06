"""上下文组装：整条还原（含引用表格）+ scope 限定 + 12000 token 整条丢弃。"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from archrag.store.sqlite import SqliteStore


@dataclass(frozen=True, slots=True)
class ContextRequest:
    """要还原进上下文的一条：分数用于超限时的丢弃顺序。"""

    clause_id: str
    score: float
    matched_kuan: int | None = None
    is_reference: bool = False


@dataclass(frozen=True, slots=True)
class ContextClause:
    """整条还原结果；tables 为整表文本。"""

    clause_id: str
    clause_no: str
    standard_id: str
    standard_name: str
    level: str
    path: tuple[str, ...]
    section_id: str
    section_clause_count: int
    matched_kuan: int | None
    is_reference: bool
    text: str
    tables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextResult:
    """可直接交给生成层的上下文。"""

    text: str
    clauses: tuple[ContextClause, ...]
    scope_qualifiers: tuple[str, ...]
    dropped: tuple[str, ...]
    token_count: int


def build_context(
    store: SqliteStore,
    requests: Sequence[ContextRequest],
    *,
    count_tokens: Callable[[str], int],
    max_tokens: int = 12000,
) -> ContextResult:
    """整条还原并按分数从低到高整条丢弃，直到不超预算。"""
    clause_ids = [request.clause_id for request in requests]
    rows = {row["clause_id"]: row for row in store.clauses_by_ids(clause_ids)}
    names = store.standard_names()
    levels = store.standard_levels()
    section_counts: dict[str, dict[str, int]] = {}
    clauses: list[ContextClause] = []
    for request in requests:
        row = rows.get(request.clause_id)
        if row is None:
            continue
        standard_id = str(row["standard_id"])
        counts = section_counts.setdefault(
            standard_id, store.section_clause_counts(standard_id)
        )
        clauses.append(
            ContextClause(
                clause_id=str(row["clause_id"]),
                clause_no=str(row["clause_no"]),
                standard_id=standard_id,
                standard_name=names.get(standard_id, standard_id),
                level=levels.get(standard_id, ""),
                path=tuple(json.loads(row["path_json"])),
                section_id=str(row["section_id"]),
                section_clause_count=counts.get(str(row["section_id"]), 0),
                matched_kuan=request.matched_kuan,
                is_reference=request.is_reference,
                text=str(row["text"]),
                tables=tuple(_render_tables(store, standard_id, str(row["clause_no"]))),
            )
        )
    scopes = _collect_scopes(store, clauses)
    kept = list(clauses)
    dropped: list[str] = []
    while kept:
        text = _render(kept, scopes)
        if count_tokens(text) <= max_tokens or len(kept) == 1:
            return ContextResult(
                text=text,
                clauses=tuple(kept),
                scope_qualifiers=tuple(scopes),
                dropped=tuple(dropped),
                token_count=count_tokens(text),
            )
        removed = kept.pop()
        dropped.append(removed.clause_id)
    empty = _render([], [])
    return ContextResult(
        text=empty,
        clauses=(),
        scope_qualifiers=(),
        dropped=tuple(dropped),
        token_count=0,
    )


def _render_tables(store: SqliteStore, standard_id: str, clause_no: str) -> list[str]:
    rendered: list[str] = []
    for entry in store.tables_for_clause(standard_id, clause_no):
        table = entry["table"]
        caption = str(table["caption"])
        notes = json.loads(str(table["notes_json"]))
        lines = [caption]
        rows = entry["rows"]
        if isinstance(rows, list):
            for row in rows:
                cells = json.loads(str(row["cells_json"]))
                lines.append(" | ".join(str(cell) for cell in cells))
        lines.extend(str(note) for note in notes)
        rendered.append("\n".join(lines))
    return rendered


def _collect_scopes(
    store: SqliteStore, clauses: Sequence[ContextClause]
) -> list[str]:
    scopes: list[str] = []
    seen: set[tuple[str, str]] = set()
    for clause in clauses:
        key = (clause.standard_id, clause.section_id)
        if key in seen:
            continue
        seen.add(key)
        for row in store.scope_chunks_for_sections(clause.standard_id, [clause.section_id]):
            scopes.append(str(row["text"]))
    return scopes


def _render(clauses: Sequence[ContextClause], scopes: Sequence[str]) -> str:
    blocks: list[str] = []
    ordered = sorted(
        enumerate(clauses),
        key=lambda item: (0 if item[1].level == "全文强制" else 1, item[0]),
    )
    for _, clause in ordered:
        header = (
            f"【{clause.standard_name} {' › '.join(clause.path)} {clause.clause_no}】"
            f"（clause_id：{clause.clause_id}）"
        )
        body = [header, clause.text]
        body.extend(clause.tables)
        if clause.matched_kuan is not None:
            body.append(f"（命中第 {clause.matched_kuan} 款）")
        if clause.is_reference:
            body.append("（关联参考，不作为结论依据）")
        blocks.append("\n".join(part for part in body if part))
    if scopes:
        blocks.append("【适用范围限定：仅作条件限定，不得作为答案依据】")
        blocks.extend(scopes)
    return "\n\n".join(blocks)
