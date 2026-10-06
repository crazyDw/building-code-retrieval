"""工作区外未规范化备份的双形态等价性与四类缺陷分类测试。"""

from __future__ import annotations

import re

import pytest

from archrag.corpus.models import DefectKind
from archrag.corpus.parser import parse_file

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_PAGE_NO_RE = re.compile(r"\s\d+\s*$")
_CLAUSE_LINE_RE = re.compile(r"^\d+\.\d+\.\d+\s")
_SECTION_LINE_RE = re.compile(r"^\d+\.\d+\s+\S")
_CHAPTER_LINE_RE = re.compile(r"^\d+\s+\S")

FILE_NAMES = [
    "民用建筑通用规范.md",
    "住宅项目规范.md",
    "钢结构通用规范.md",
    "混凝土结构通用规范.md",
    "砌体结构通用规范.md",
]


def _backup_path(backup_dir, file_name: str):
    stem = file_name[: -len(".md")]
    return backup_dir / stem / file_name


def _raw_defects(text: str) -> dict[str, object]:
    """不依赖解析器，按行独立算出四类缺陷的期望值。"""
    chapter_levels: list[int] = []
    section_levels: list[int] = []
    toc_lines: list[int] = []
    clause_lines: list[int] = []
    in_toc = False
    toc_closed = False
    for index, line in enumerate(text.splitlines(), start=1):
        match = _HEADING_RE.match(line.strip())
        if match is None:
            continue
        marks, body = match.group(1), match.group(2).strip()
        if body.replace(" ", "") == "目次":
            in_toc = True
            continue
        if in_toc and not toc_closed:
            if _PAGE_NO_RE.search(body):
                toc_lines.append(index)
                continue
            if _CHAPTER_LINE_RE.match(body) or _SECTION_LINE_RE.match(body):
                toc_closed = True
                in_toc = False
            else:
                continue
        if _CLAUSE_LINE_RE.match(body):
            clause_lines.append(index)
        elif _SECTION_LINE_RE.match(body):
            section_levels.append(len(marks))
        elif _CHAPTER_LINE_RE.match(body):
            chapter_levels.append(len(marks))
    return {
        "chapter_levels": chapter_levels,
        "section_levels": section_levels,
        "toc_lines": toc_lines,
        "clause_lines": clause_lines,
    }


@pytest.mark.parametrize("file_name", FILE_NAMES)
def test_backup_is_equivalent_to_normalized_source(
    file_name, standard_map, corpus_dir, backup_markdown_dir
) -> None:
    backup = _backup_path(backup_markdown_dir, file_name)
    if not backup.is_file():
        pytest.skip(f"备份缺少 {file_name}")
    normalized = parse_file(corpus_dir / file_name, standard_map[file_name])
    original = parse_file(backup, standard_map[file_name])
    assert [c.clause_no for c in original.clauses] == [c.clause_no for c in normalized.clauses]
    assert [(c.chapter_no, c.title) for c in original.chapters] == [
        (c.chapter_no, c.title) for c in normalized.chapters
    ]
    assert [(s.section_id, s.title) for s in original.sections] == [
        (s.section_id, s.title) for s in normalized.sections
    ]
    assert [c.text for c in original.clauses] == [c.text for c in normalized.clauses]
    assert [
        (len(c.kuans), [len(k.items) for k in c.kuans]) for c in original.clauses
    ] == [(len(c.kuans), [len(k.items) for k in c.kuans]) for c in normalized.clauses]


@pytest.mark.parametrize("file_name", FILE_NAMES)
def test_backup_defects_are_classified(file_name, backup_markdown_dir) -> None:
    backup = _backup_path(backup_markdown_dir, file_name)
    if not backup.is_file():
        pytest.skip(f"备份缺少 {file_name}")
    text = backup.read_text(encoding="utf-8")
    expected_raw = _raw_defects(text)
    parsed = parse_file(backup, standard_map_for_file(backup))

    clause_lines = sorted(
        issue.line
        for issue in parsed.issues
        if issue.kind is DefectKind.CLAUSE_MARKED_AS_HEADING
    )
    toc_lines = sorted(
        issue.line for issue in parsed.issues if issue.kind is DefectKind.TOC_ENTRY_MARKED
    )
    assert clause_lines == expected_raw["clause_lines"]
    assert toc_lines == expected_raw["toc_lines"]

    chapter_levels = expected_raw["chapter_levels"]
    section_levels = expected_raw["section_levels"]
    kinds = {issue.kind for issue in parsed.issues}
    assert (DefectKind.CHAPTER_MARK_MIXED in kinds) == (len(set(chapter_levels)) > 1)
    assert (DefectKind.CHAPTER_SECTION_SAME_LEVEL in kinds) == (
        bool(chapter_levels)
        and bool(section_levels)
        and set(chapter_levels) == set(section_levels)
    )


def standard_map_for_file(path):
    """备份测试只需一个 Standard；标准号取自文件名。"""
    from archrag.corpus.models import Standard

    return Standard(
        standard_id="TEST",
        name=path.stem,
        file_name=path.name,
    )
