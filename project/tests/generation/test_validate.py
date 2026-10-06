"""生成校验单元测试。"""

from __future__ import annotations

from archrag.generation import validate
from archrag.generation.prompts import DERIVATION_MARKER, ORIGINAL_MARKER

SOURCE = (
    "5.3.9 公共楼梯踏步的最小宽度和最大高度应符合表 5.3.9 的规定。"
    "螺旋楼梯和扇形踏步离内侧扶手中心 0.25m 处的踏步宽度不应小于 0.22m。"
)
ALLOWED = ["GB 55031-2022_5.3.9"]


def _answer(derivation: str, original: str) -> str:
    return f"{DERIVATION_MARKER}\n{derivation}\n{ORIGINAL_MARKER}\n{original}"


def test_split_sections_handles_markers() -> None:
    derivation, original = validate.split_sections(_answer("推导", "原文"))
    assert derivation == "推导"
    assert original == "原文"
    assert validate.split_sections("没有标记") == ("没有标记", "")


def test_split_sections_tolerates_incomplete_markers() -> None:
    derivation, original = validate.split_sections("<!--推导\n推导<!--原文\n原文")
    assert derivation == "推导"
    assert original == "原文"


def test_extract_values_ignores_ids_and_clause_numbers() -> None:
    text = (
        "见表 5.3.9-1、第 3.2.1 条与 GB 55031-2022，取值 0.25m 和 6 层。"
        "[[clause:GB 55031-2022_5.3.9]]"
    )
    assert validate.extract_values(text) == ("0.25m", "6层")


def test_valid_answer_passes() -> None:
    result = validate.validate_answer(
        _answer(
            "按 5.3.9，公共楼梯踏步最小宽度与最大高度依表取值。[[clause:GB 55031-2022_5.3.9]]",
            f"{SOURCE}[[clause:GB 55031-2022_5.3.9]]",
        ),
        allowed_clause_ids=ALLOWED,
        source_texts=[SOURCE],
    )
    assert result.violations == ()
    assert result.citations == ("GB 55031-2022_5.3.9",)


def test_tampered_value_is_reported() -> None:
    result = validate.validate_answer(
        _answer(
            "按条文取值。[[clause:GB 55031-2022_5.3.9]]",
            "踏步宽度不应小于 0.30m。[[clause:GB 55031-2022_5.3.9]]",
        ),
        allowed_clause_ids=ALLOWED,
        source_texts=[SOURCE],
    )
    assert "original_value_mismatch:0.30m" in result.violations


def test_unknown_citation_is_reported() -> None:
    result = validate.validate_answer(
        _answer(
            "推导。[[clause:GB 9999-2025_1.1.1]]",
            f"{SOURCE}[[clause:GB 9999-2025_1.1.1]]",
        ),
        allowed_clause_ids=ALLOWED,
        source_texts=[SOURCE],
    )
    assert any(item.startswith("unknown_citation:") for item in result.violations)


def test_forbidden_wording_is_reported() -> None:
    result = validate.validate_answer(
        _answer(
            "该做法满足规范要求。[[clause:GB 55031-2022_5.3.9]]",
            f"{SOURCE}[[clause:GB 55031-2022_5.3.9]]",
        ),
        allowed_clause_ids=ALLOWED,
        source_texts=[SOURCE],
    )
    assert "forbidden_wording" in result.violations


def test_note_and_scope_as_basis_are_reported() -> None:
    note = validate.validate_answer(
        _answer(
            "根据注：表中数值可直接采用。[[clause:GB 55031-2022_5.3.9]]",
            f"{SOURCE}[[clause:GB 55031-2022_5.3.9]]",
        ),
        allowed_clause_ids=ALLOWED,
        source_texts=[SOURCE],
    )
    assert "note_as_basis" in note.violations
    scope = validate.validate_answer(
        _answer(
            "依据适用范围可以确定。[[clause:GB 55031-2022_5.3.9]]",
            f"{SOURCE}[[clause:GB 55031-2022_5.3.9]]",
        ),
        allowed_clause_ids=ALLOWED,
        source_texts=[SOURCE],
    )
    assert "scope_as_basis" in scope.violations


def test_derived_number_requires_inputs() -> None:
    without = validate.validate_answer(
        _answer(
            "净高约为 2.2m。[[clause:GB 55031-2022_5.3.9]]",
            f"{SOURCE}[[clause:GB 55031-2022_5.3.9]]",
        ),
        allowed_clause_ids=ALLOWED,
        source_texts=[SOURCE],
    )
    assert "missing_inputs" in without.violations
    with_inputs = validate.validate_answer(
        _answer(
            "按层数 6、层高 3.0m 推算，净高约为 2.2m。[[clause:GB 55031-2022_5.3.9]]",
            f"{SOURCE}[[clause:GB 55031-2022_5.3.9]]",
        ),
        allowed_clause_ids=ALLOWED,
        source_texts=[SOURCE],
        input_values=["6层", "3.0m"],
    )
    assert "missing_inputs" not in with_inputs.violations


def test_restating_source_values_needs_no_inputs() -> None:
    result = validate.validate_answer(
        _answer(
            "条文给出 0.25m 与 0.22m 的限值。[[clause:GB 55031-2022_5.3.9]]",
            f"{SOURCE}[[clause:GB 55031-2022_5.3.9]]",
        ),
        allowed_clause_ids=ALLOWED,
        source_texts=[SOURCE],
    )
    assert "missing_inputs" not in result.violations


def test_clarification_without_citations_is_accepted() -> None:
    result = validate.validate_answer(
        "您想先了解层高要求，还是防火分区划分？",
        allowed_clause_ids=ALLOWED,
        source_texts=[SOURCE],
        clarification=True,
    )
    assert result.violations == ()


def test_missing_markers_are_reported() -> None:
    result = validate.validate_answer(
        "没有标记的输出",
        allowed_clause_ids=ALLOWED,
        source_texts=[SOURCE],
    )
    assert "missing_original_marker" in result.violations
    assert "missing_citations" in result.violations
