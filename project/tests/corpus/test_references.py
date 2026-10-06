"""引用图抽取测试。"""

from __future__ import annotations

from archrag.corpus.models import RefType, Standard
from archrag.corpus.parser import parse_text
from archrag.corpus.references import extract_references

EXPECTED_REF_COUNTS = {
    "民用建筑通用规范.md": 4,
    "住宅项目规范.md": 10,
    "钢结构通用规范.md": 1,
    "混凝土结构通用规范.md": 10,
    "砌体结构通用规范.md": 5,
}


def test_real_reference_counts(parsed_corpus) -> None:
    actual = {
        name: len(extract_references(parsed)) for name, parsed in parsed_corpus.items()
    }
    assert actual == EXPECTED_REF_COUNTS
    assert sum(actual.values()) == 30


def test_table_edges_are_complete(parsed_corpus) -> None:
    parsed = parsed_corpus["住宅项目规范.md"]
    edges = extract_references(parsed)
    table_edges = [edge for edge in edges if edge.ref_type is RefType.TABLE]
    assert len(table_edges) == 10
    known_tables = {table.table_id for table in parsed.tables}
    assert all(edge.dst_id in known_tables for edge in table_edges)


def test_clause_edges_resolve_to_existing_clauses(parsed_corpus) -> None:
    known: set[str] = set()
    for parsed in parsed_corpus.values():
        known.update(clause.clause_id for clause in parsed.clauses)
    clause_edges = [
        edge
        for parsed in parsed_corpus.values()
        for edge in extract_references(parsed)
        if edge.ref_type is RefType.CLAUSE
    ]
    assert len(clause_edges) == 4
    assert all(edge.dst_id in known for edge in clause_edges)


def test_cross_standard_reference_is_separate_type() -> None:
    standard = Standard(standard_id="GB 55000-2025", name="测试规范", file_name="t.md")
    text = "# 1 总 则\n\n1.0.1 设备选型应符合 GB 55031-2022 的规定。\n"
    edges = extract_references(parse_text(text, standard))
    assert [(edge.ref_type, edge.dst_id, edge.dst_standard_id) for edge in edges] == [
        (RefType.STANDARD, "GB 55031-2022", "GB 55031-2022")
    ]
