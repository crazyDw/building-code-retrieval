"""条款目录：条文、节内条文、规范章节树与条款号搜索。"""

from __future__ import annotations

import json
import sqlite3

from fastapi import APIRouter, HTTPException, Query

from archrag.api.deps import StateDep
from archrag.store.sqlite import SqliteStore

router = APIRouter()


def _table_payloads(
    store: SqliteStore, standard_id: str, clause_no: str
) -> list[dict]:
    payloads: list[dict] = []
    for entry in store.tables_for_clause(standard_id, clause_no):
        table = entry["table"]
        rows = entry["rows"]
        payloads.append(
            {
                "table_id": str(table["table_id"]),
                "caption": str(table["caption"]),
                "notes": json.loads(str(table["notes_json"])),
                "source_line": int(table["source_line"]),
                "rows": [
                    json.loads(str(row["cells_json"]))
                    for row in rows
                    if isinstance(row, dict)
                ],
            }
        )
    return payloads


def clause_payload(store: SqliteStore, row: sqlite3.Row) -> dict:
    clause_id = str(row["clause_id"])
    parts = store.clause_parts_for([clause_id])
    kuans: dict[int, dict] = {}
    for part in parts:
        if part["part_type"] == "kuan":
            kuans[int(part["part_no"])] = {
                "kuan_no": int(part["part_no"]),
                "text": str(part["text"]),
                "items": [],
            }
        elif part["part_type"] == "item":
            kuan = kuans.setdefault(
                int(part["kuan_no"] or 0),
                {"kuan_no": int(part["kuan_no"] or 0), "text": "", "items": []},
            )
            kuan["items"].append(
                {"item_no": int(part["part_no"]), "text": str(part["text"])}
            )
    return {
        "clause_id": clause_id,
        "clause_no": str(row["clause_no"]),
        "standard_id": str(row["standard_id"]),
        "section_id": str(row["section_id"]),
        "chapter_no": int(row["chapter_no"]),
        "path": json.loads(str(row["path_json"])),
        "text": str(row["text"]),
        "intro": str(row["intro"]),
        "kuans": [kuans[key] for key in sorted(kuans)],
        "has_table": bool(row["has_table"]),
        "source_line": int(row["source_line"]),
        "tables": _table_payloads(store, str(row["standard_id"]), str(row["clause_no"])),
    }


@router.get("/api/clause/{clause_id}")
def get_clause(clause_id: str, state: StateDep) -> dict:
    row = state.store.clause_row(clause_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "clause_not_found"})
    return clause_payload(state.store, row)


@router.get("/api/clauses")
def get_clauses(
    state: StateDep,
    standard_id: str | None = None,
    section_no: str | None = None,
) -> dict:
    if standard_id is None or section_no is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "missing_parameter", "message": "需要 standard_id 与 section_no"},
        )
    rows = state.store.clauses_in_section(standard_id, section_no)
    return {
        "standard_id": standard_id,
        "section_no": section_no,
        "count": len(rows),
        "items": [
            {
                "clause_id": str(row["clause_id"]),
                "clause_no": str(row["clause_no"]),
                "text": str(row["text"]),
                "has_table": bool(row["has_table"]),
            }
            for row in rows
        ],
    }


@router.get("/api/standards")
def get_standards(state: StateDep) -> dict:
    items: list[dict] = []
    for standard in state.store.list_standards():
        standard_id = str(standard["standard_id"])
        chapters = []
        for chapter in state.store.chapters_for(standard_id):
            chapters.append(
                {
                    "chapter_no": int(chapter["chapter_no"]),
                    "title": str(chapter["title"]),
                    "sections": [
                        {
                            "section_id": str(section["section_id"]),
                            "title": str(section["title"]),
                            "clause_count": int(section["clause_count"]),
                        }
                        for section in state.store.sections_for(standard_id)
                        if int(section["chapter_no"]) == int(chapter["chapter_no"])
                    ],
                }
            )
        items.append(
            {
                "standard_id": standard_id,
                "name": str(standard["name"]),
                "level": str(standard["level"]),
                "effective_date": standard["effective_date"],
                "superseded_by": standard["superseded_by"],
                "chapters": chapters,
            }
        )
    return {"items": items}


@router.get("/api/search")
def search_clause(
    state: StateDep,
    clause_no: str = Query(...),
    standard_id: str | None = None,
) -> dict:
    clause_ids = state.store.clause_ids_by_no(clause_no, standard_id=standard_id)
    rows = state.store.clauses_by_ids(clause_ids)
    return {
        "clause_no": clause_no,
        "count": len(rows),
        "items": [clause_payload(state.store, row) for row in rows],
    }
