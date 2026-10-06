"""LaTeX 符号还原与符号→中文术语候选测试。"""

from __future__ import annotations

import pytest

from archrag.corpus.latex import extract, restore

EXPECTED_COUNTS = {
    "民用建筑通用规范.md": 1,
    "住宅项目规范.md": 28,
    "钢结构通用规范.md": 5,
    "混凝土结构通用规范.md": 33,
    "砌体结构通用规范.md": 30,
}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$0.50 \\, m^{2}$", "0.50 m2"),
        ("$E_{h,\\text{av}}$", "Eh,av"),
        ("$L_{\\text{eq,T/1}}$", "Leq,T/1"),
        ("$\\delta_{gt}$", "δgt"),
        ("$\\geqslant 16.0$", "≥16.0"),
        ("$2\\phi10$", "2φ10"),
        ("$100^{\\circ}$", "100°"),
        ("$-25 \\mu m$", "-25 μm"),
        ("$\\sigma_0/f_V$", "σ0/fV"),
    ],
)
def test_symbol_restoration(raw: str, expected: str) -> None:
    assert restore(raw) == expected


def test_real_formula_is_kept_verbatim() -> None:
    raw = "$\\frac{a}{b}=c$"
    assert restore(raw) == raw
    occurrence = extract(raw)[0]
    assert occurrence.is_formula is True
    assert occurrence.restored == raw


def test_occurrence_counts_match_latex_census(parsed_corpus) -> None:
    actual = {
        name: sum(1 for item in parsed.latex_occurrences if not item.is_formula)
        for name, parsed in parsed_corpus.items()
    }
    assert actual == EXPECTED_COUNTS
    assert sum(actual.values()) == 97
    formulas = {
        name: sum(1 for item in parsed.latex_occurrences if item.is_formula)
        for name, parsed in parsed_corpus.items()
    }
    assert formulas == {
        "民用建筑通用规范.md": 0,
        "住宅项目规范.md": 0,
        "钢结构通用规范.md": 0,
        "混凝土结构通用规范.md": 0,
        "砌体结构通用规范.md": 1,
    }


def test_symbol_candidates_capture_nearby_chinese_terms(parsed_corpus) -> None:
    candidates = {
        candidate.symbol: candidate.term
        for candidate in parsed_corpus["住宅项目规范.md"].symbol_candidates
    }
    assert candidates.get("Eh,av") == "平均水平照度"
    assert candidates.get("Ra") == "一般显色指数"


def test_clause_texts_are_restored(parsed_corpus) -> None:
    dollar_clauses = [
        (name, clause.clause_no)
        for name, parsed in parsed_corpus.items()
        for clause in parsed.clauses
        if "$" in clause.text
    ]
    assert dollar_clauses == [("砌体结构通用规范.md", "3.4.2")]
    formula_clause = parsed_corpus["砌体结构通用规范.md"].clause_by_no("3.4.2")
    assert "\\tag {3.4.2}" in formula_clause.text
    assert "\\mathrm{VE}" in formula_clause.text
    clause = next(
        clause
        for clause in parsed_corpus["住宅项目规范.md"].clauses
        if "0.50 m2" in clause.text
    )
    assert "0.50 \\, m^{2}" not in clause.text
