"""五级层级计数与条号连续性测试（5 份真实语料）。"""

from __future__ import annotations

import pytest

from archrag.corpus.models import Standard
from archrag.corpus.parser import parse_text

# 款数为解析口径：粗测脚本把 2 条带编号的表格注续行（住宅 L168、混凝土 L179）
# 计为款；按铁律 12「注」属表格，解析器归入表注，故精确款数为 436。
EXPECTED = {
    "民用建筑通用规范.md": (6, 26, 142, 78, 0),
    "住宅项目规范.md": (7, 16, 122, 90, 0),
    "钢结构通用规范.md": (8, 21, 107, 70, 0),
    "混凝土结构通用规范.md": (6, 16, 99, 126, 7),
    "砌体结构通用规范.md": (6, 12, 84, 72, 0),
}

TEST_STANDARD = Standard(
    standard_id="GB 55000-2025",
    name="测试规范",
    file_name="test.md",
)


def _counts(parsed) -> tuple[int, int, int, int, int]:
    return (
        len(parsed.chapters),
        len(parsed.sections),
        len(parsed.clauses),
        parsed.kuan_count(),
        parsed.xiang_count(),
    )


@pytest.mark.parametrize(("file_name", "expected"), EXPECTED.items())
def test_counts_per_standard(file_name, expected, parsed_corpus) -> None:
    assert _counts(parsed_corpus[file_name]) == expected


def test_corpus_totals(parsed_corpus) -> None:
    totals = [
        sum(values)
        for values in zip(*(_counts(p) for p in parsed_corpus.values()), strict=True)
    ]
    assert tuple(totals) == (33, 91, 554, 436, 7)


@pytest.mark.parametrize("file_name", EXPECTED)
def test_clause_numbers_have_no_gaps(file_name, parsed_corpus) -> None:
    assert parsed_corpus[file_name].clause_gaps() == ()


def test_clause_sorting_uses_numeric_components(parsed_corpus) -> None:
    clauses = parsed_corpus["民用建筑通用规范.md"].clauses
    order = [clause.clause_no for clause in clauses]
    assert order.index("5.3.9") < order.index("5.3.10")
    sorted_order = [clause.clause_no for clause in sorted(clauses, key=lambda c: c.num_key)]
    assert sorted_order == order


def test_steel_structure_body_starts_after_toc(parsed_corpus) -> None:
    parsed = parsed_corpus["钢结构通用规范.md"]
    toc = next(item for item in parsed.front_matter if item.kind == "目次")
    assert toc.end_line == 53
    assert parsed.chapters[0].source_line == 54


def test_cross_chapter_transitions_are_accepted() -> None:
    text = (
        "# 1 总 则\n\n1.0.1 甲。\n\n1.0.2 乙。\n\n"
        "# 2 基本规定\n\n## 2.1 一般规定\n\n2.1.1 丙。\n\n"
        "## 2.2 其他规定\n\n2.2.1 丁。\n\n"
        "# 3 材料\n\n3.0.1 戊。\n"
    )
    parsed = parse_text(text, TEST_STANDARD)
    assert parsed.clause_gaps() == ()


def test_clause_number_gap_is_reported() -> None:
    text = "# 1 总 则\n\n1.0.1 甲。\n\n1.0.3 丙。\n"
    parsed = parse_text(text, TEST_STANDARD)
    assert parsed.clause_gaps() == (("1.0.1", "1.0.3"),)


def test_section_gap_within_chapter_is_reported() -> None:
    text = (
        "# 2 基本规定\n\n## 2.1 一般\n\n2.1.1 甲。\n\n"
        "## 2.3 其他\n\n2.3.1 乙。\n"
    )
    parsed = parse_text(text, TEST_STANDARD)
    assert parsed.clause_gaps() == (("2.1.1", "2.3.1"),)
