"""HTML 表格解析、合并单元格展开与注关联测试。"""

from __future__ import annotations

from archrag.corpus.tables import parse_html_table

EXPECTED_TABLES = {
    "民用建筑通用规范.md": 2,
    "住宅项目规范.md": 10,
    "钢结构通用规范.md": 0,
    "混凝土结构通用规范.md": 10,
    "砌体结构通用规范.md": 5,
}

EXPECTED_NOTE_BLOCKS = {
    "民用建筑通用规范.md": 1,
    "住宅项目规范.md": 3,
    "钢结构通用规范.md": 0,
    "混凝土结构通用规范.md": 4,
    "砌体结构通用规范.md": 0,
}


def test_table_counts(parsed_corpus) -> None:
    actual = {name: len(parsed.tables) for name, parsed in parsed_corpus.items()}
    assert actual == EXPECTED_TABLES
    assert sum(actual.values()) == 27


def test_note_block_counts(parsed_corpus) -> None:
    actual = {
        name: sum(len(table.notes) for table in parsed.tables)
        for name, parsed in parsed_corpus.items()
    }
    assert actual == EXPECTED_NOTE_BLOCKS
    assert sum(actual.values()) == 8


def test_clause_can_reference_multiple_tables(parsed_corpus) -> None:
    clause = parsed_corpus["住宅项目规范.md"].clause_by_no("3.1.1")
    assert [table.table_id for table in clause.tables] == ["表 3.1.1-1", "表 3.1.1-2"]


def test_tables_are_rectangular_and_labeled(parsed_corpus) -> None:
    for parsed in parsed_corpus.values():
        for table in parsed.tables:
            assert table.table_id.startswith("表 ")
            assert table.caption.startswith(("表", "续表"))
            assert table.rows
            widths = {len(row) for row in table.rows}
            assert len(widths) == 1


def test_rowspan_and_colspan_expansion(parsed_corpus) -> None:
    table = next(
        item for item in parsed_corpus["砌体结构通用规范.md"].tables if item.source_line == 106
    )
    assert len(table.rows) == 5
    assert table.rows[0] == (
        "环境类别",
        "冻融环境",
        "抗冻性能",
        "抗冻性能",
        "抗冻性能",
        "块材最低强度等级",
        "块材最低强度等级",
        "块材最低强度等级",
    )
    assert table.rows[2] == ("3", "微冻地区", "F25", "≤5", "≤20", "MU15", "MU20", "MU10")


def test_rowspan_carries_into_following_rows(parsed_corpus) -> None:
    table = next(
        item
        for item in parsed_corpus["混凝土结构通用规范.md"].tables
        if item.source_line == 137
    )
    assert table.rows[2] == ("干燥环境", "0.30", "0.06")
    assert table.rows[3] == ("潮湿但不含氯离子的环境", "0.20", "0.06")


def test_colspan_expands_header(parsed_corpus) -> None:
    table = next(
        item for item in parsed_corpus["住宅项目规范.md"].tables if item.source_line == 90
    )
    assert table.rows[0] == ("类别", "类别", "设计工作年限")
    assert table.rows[1] == ("建筑结构", "建筑结构", "不应低于50年")


def test_notes_are_joined_into_one_block(parsed_corpus) -> None:
    table = next(
        item for item in parsed_corpus["住宅项目规范.md"].tables if item.source_line == 165
    )
    assert len(table.notes) == 1
    assert "城镇道路的边缘是指道路红线" in table.notes[0]
    assert "附属道路的边缘是指路面边线" in table.notes[0]


def test_notes_are_restored_and_attached(parsed_corpus) -> None:
    table = next(
        item
        for item in parsed_corpus["混凝土结构通用规范.md"].tables
        if item.source_line == 339
    )
    assert table.notes == (
        "注：表中 d 为柱纵向普通钢筋的直径（mm）；柱根指柱底部嵌固部位的加密区范围。",
    )


def test_parser_handles_empty_and_simple_fragments() -> None:
    assert parse_html_table("<table></table>") == ()
    assert parse_html_table("<table><tr><td>甲</td><td>乙</td></tr></table>") == (
        ("甲", "乙"),
    )
