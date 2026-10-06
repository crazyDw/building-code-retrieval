"""引用图：抽取「条→表 / 条→条 / 条→标准」边。"""

from __future__ import annotations

import re

from archrag.corpus.models import ParsedStandard, Reference, RefType

_TABLE_RE = re.compile(r"表\s*(\d+\.\d+\.\d+(?:-\d+)?)")
_CLAUSE_RE = re.compile(r"第\s*(\d+\.\d+\.\d+)\s*条")
_STANDARD_RE = re.compile(r"(GB\s*\d{5}(?:-\d{4})?)")


def extract_references(parsed: ParsedStandard) -> tuple[Reference, ...]:
    """按条文文本与表关联抽取引用边，顺序稳定且去重。"""
    by_no = {clause.clause_no: clause for clause in parsed.clauses}
    seen: set[tuple[str, str, str]] = set()
    result: list[Reference] = []

    def add(reference: Reference) -> None:
        key = (reference.src_clause_id, reference.ref_type.value, reference.dst_id)
        if key not in seen:
            seen.add(key)
            result.append(reference)

    for clause in parsed.clauses:
        for table in clause.tables:
            add(
                Reference(
                    src_clause_id=clause.clause_id,
                    ref_type=RefType.TABLE,
                    dst_id=table.table_id,
                    dst_standard_id=parsed.standard.standard_id,
                )
            )
        for match in _TABLE_RE.finditer(clause.text):
            add(
                Reference(
                    src_clause_id=clause.clause_id,
                    ref_type=RefType.TABLE,
                    dst_id=f"表 {match.group(1)}",
                    dst_standard_id=parsed.standard.standard_id,
                )
            )
        for match in _CLAUSE_RE.finditer(clause.text):
            clause_no = match.group(1)
            target = by_no.get(clause_no)
            dst_id = (
                target.clause_id
                if target is not None
                else f"{parsed.standard.standard_id}_{clause_no}"
            )
            add(
                Reference(
                    src_clause_id=clause.clause_id,
                    ref_type=RefType.CLAUSE,
                    dst_id=dst_id,
                    dst_standard_id=parsed.standard.standard_id,
                )
            )
        for match in _STANDARD_RE.finditer(clause.text):
            standard_id = re.sub(r"\s+", " ", match.group(1)).strip()
            add(
                Reference(
                    src_clause_id=clause.clause_id,
                    ref_type=RefType.STANDARD,
                    dst_id=standard_id,
                    dst_standard_id=standard_id,
                )
            )
    return tuple(result)
