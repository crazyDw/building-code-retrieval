"""HTML 表格解析：colspan/rowspan 展开、表题与「注：」关联。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

_CAPTION_RE = re.compile(r"^\s*(续?表)\s*(\d+(?:\.\d+){2}(?:-\d+)?)\s*(.*)$")
_NOTE_RE = re.compile(r"^\s*注\s*[：:]")
_CLAUSE_NO_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True, slots=True)
class Caption:
    """表题行：`表 3.1.1-2 低层…` / `续表 3.1.8`。"""

    table_id: str
    title: str
    is_continuation: bool


def parse_caption(line: str) -> Caption | None:
    """解析表题行；不是表题时返回 None。"""
    match = _CAPTION_RE.match(line)
    if match is None:
        return None
    table_id = f"表 {match.group(2)}"
    return Caption(
        table_id=table_id,
        title=match.group(3).strip(),
        is_continuation=match.group(1) == "续表",
    )


def table_clause_no(table_id: str) -> str | None:
    """从表号推出所属条号（`表 3.1.1-2` → `3.1.1`）。"""
    match = _CLAUSE_NO_RE.search(table_id)
    if match is None:
        return None
    return match.group(0)


def is_note_line(line: str) -> bool:
    """判断是否为 `注：` 起始行（带编号的注也以「注：」开头）。"""
    return _NOTE_RE.match(line) is not None


def parse_html_table(fragment: str) -> tuple[tuple[str, ...], ...]:
    """解析一段 HTML 表格并展开合并单元格。"""
    parser = _TableHtmlParser()
    parser.feed(fragment)
    parser.close()
    return _expand(parser.rows)


def _expand(
    rows: list[list[tuple[str, int, int]]],
) -> tuple[tuple[str, ...], ...]:
    """按 colspan/rowspan 把稀疏单元格铺满矩形网格。"""
    carried: dict[tuple[int, int], str] = {}
    grid: list[list[str]] = []
    for row_index, cells in enumerate(rows):
        row: list[str] = []
        column = 0
        while (row_index, column) in carried:
            row.append(carried.pop((row_index, column)))
            column += 1
        for text, colspan, rowspan in cells:
            while (row_index, column) in carried:
                row.append(carried.pop((row_index, column)))
                column += 1
            for _ in range(colspan):
                row.append(text)
                if rowspan > 1:
                    for offset in range(1, rowspan):
                        carried[(row_index + offset, column)] = text
                column += 1
        while (row_index, column) in carried:
            row.append(carried.pop((row_index, column)))
            column += 1
        grid.append(row)
    return tuple(tuple(row) for row in grid)


class _TableHtmlParser(HTMLParser):
    """收集 `<tr>` 下的单元格文本与合并属性。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, int, int]]] = []
        self._row: list[tuple[str, int, int]] | None = None
        self._parts: list[str] | None = None
        self._colspan = 1
        self._rowspan = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            attributes = dict(attrs)
            self._parts = []
            self._colspan = _to_int(attributes.get("colspan"))
            self._rowspan = _to_int(attributes.get("rowspan"))
        elif tag == "br" and self._parts is not None:
            self._parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._parts is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._parts is not None and self._row is not None:
            text = re.sub(r"\s+", " ", "".join(self._parts)).strip()
            self._row.append((text, self._colspan, self._rowspan))
            self._parts = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def close(self) -> None:
        super().close()
        if self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _to_int(raw: str | None) -> int:
    if raw is None:
        return 1
    try:
        value = int(raw)
    except ValueError:
        return 1
    return value if value > 0 else 1
