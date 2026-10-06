"""查询理解测试：短路、别名、数值、改写触发、扩展与宽泛判定。"""

from __future__ import annotations

import pytest

from archrag.retrieval.query import (
    expand_terms,
    extract_numbers,
    match_standard_aliases,
    needs_rewrite,
    plan_query,
    strip_numbers,
)

ALIASES = {
    "GB 55031-2022": "GB 55031-2022",
    "民用建筑通用规范": "GB 55031-2022",
    "民用建筑": "GB 55031-2022",
    "住宅": "GB 55038-2025",
    "住宅项目规范": "GB 55038-2025",
}

EXPANSIONS = [("Eh,av", "平均水平照度"), ("喷淋", "自动灭火系统")]


@pytest.mark.parametrize(
    "text",
    ["5.3.9", "第5.3.9条", " 5.3.9 ", "GB 55031-2022 第5.3.9条"],
)
def test_clause_shortcut_triggers(text: str) -> None:
    plan = plan_query(text)
    assert plan.clause_no == "5.3.9"


@pytest.mark.parametrize("text", ["5.3.9 的踏步宽度", "请查 5.3.9 和 5.3.10", "楼梯 5.3.9"])
def test_clause_shortcut_requires_pure_number(text: str) -> None:
    assert plan_query(text).clause_no is None


def test_clause_query_can_carry_standard() -> None:
    plan = plan_query("GB 55031-2022 第5.3.9条")
    assert plan.clause_standard_id == "GB 55031-2022"


def test_alias_requires_full_run_match() -> None:
    assert match_standard_aliases("这个防火门有什么要求", ALIASES) == ()
    assert match_standard_aliases("住宅 楼梯踏步宽度", ALIASES) == ("GB 55038-2025",)
    assert match_standard_aliases("民用建筑通用规范里楼梯要求", ALIASES) == ()


def test_alias_matches_standard_id_token() -> None:
    assert match_standard_aliases("GB 55031-2022 楼梯要求", ALIASES) == ("GB 55031-2022",)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("层高3.0m时楼梯净高", [(3.0, "m")]),
        ("层数6层", [(6.0, "层")]),
        ("第5.3.9条", []),
        ("楼梯宽度不小于0.26m", [(0.26, "m")]),
    ],
)
def test_number_extraction(text: str, expected: list[tuple[float, str | None]]) -> None:
    numbers = extract_numbers(text)
    assert [(item.value, item.unit) for item in numbers] == expected


def test_number_stripping_keeps_clause_numbers() -> None:
    assert strip_numbers("层高3.0m时楼梯净高") == "层高时楼梯净高"
    assert strip_numbers("第5.3.9条的要求") == "第5.3.9条的要求"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("这个防火门", True),
        ("楼梯宽度", True),
        ("该条如何理解", True),
        ("高层住宅楼梯踏步最小宽度是多少", False),
    ],
)
def test_rewrite_trigger(text: str, expected: bool) -> None:
    assert needs_rewrite(text) is expected


def test_rewrite_is_applied_only_when_needed() -> None:
    calls: list[str] = []

    def rewriter(text: str) -> str:
        calls.append(text)
        return "独立问题"

    plan = plan_query("这个防火门", alias_index=ALIASES, rewriter=rewriter)
    assert plan.rewrite_needed is True and plan.rewrite_used is True
    assert plan.retrieval_text == "独立问题"
    plan = plan_query("高层住宅楼梯踏步最小宽度是多少", rewriter=rewriter)
    assert plan.rewrite_needed is False and plan.rewrite_used is False
    assert calls == ["这个防火门"]


def test_expand_terms_is_bidirectional() -> None:
    assert expand_terms("平均水平照度要求", EXPANSIONS) == ("Eh,av",)
    assert expand_terms("Eh,av 怎么取值", EXPANSIONS) == ("平均水平照度",)


def test_plan_appends_expansions_and_strips_numbers() -> None:
    plan = plan_query("喷淋系统3.0m间距要求", expansions=EXPANSIONS)
    assert "自动灭火系统" in plan.retrieval_text
    assert "3.0m" not in plan.retrieval_text
    assert [number.value for number in plan.numbers] == [3.0]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("有什么要求", True),
        ("建筑防火设计有什么要求", True),
        ("楼梯踏步最小宽度是多少", False),
        ("住宅 有什么要求", False),
        ("层高3.0m有什么要求", True),
        ("6层住宅该注意什么", True),
    ],
)
def test_broad_question_flag(text: str, expected: bool) -> None:
    assert plan_query(text, alias_index=ALIASES).is_broad is expected
