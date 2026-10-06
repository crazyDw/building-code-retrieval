"""语料解析器：按行首编号形态解析章/节/条/款/项，容错四类转换缺陷。

约束（AGENTS.md 铁律 8/9/10）：不改写源文件；层级不看 `#` 数量；
标题内版式空格只在内存中归一化；条号保留数值分量排序键。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from archrag.corpus import latex, tables
from archrag.corpus.models import (
    Chapter,
    Clause,
    DefectKind,
    FrontMatter,
    ImagePlaceholder,
    Kuan,
    ParsedStandard,
    ParseIssue,
    ScopeBlock,
    Section,
    Standard,
    Table,
    Term,
    Xiang,
)

_PREFACE_TITLE = "前言"
_TOC_TITLE = "目次"

_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s*(?P<text>.*)$")
_CLAUSE_RE = re.compile(r"^(?P<a>\d+)\.(?P<b>\d+)\.(?P<c>\d+)(?:\s+|$)(?P<rest>.*)$")
_SECTION_RE = re.compile(r"^(?P<a>\d+)\.(?P<b>\d+)(?:\s+|$)(?P<rest>.*)$")
_CHAPTER_RE = re.compile(r"^(?P<a>\d+)(?:\s+|$)(?P<rest>.*)$")
_KUAN_RE = re.compile(r"^(?P<no>\d+)\s+(?P<rest>\S.*)$")
_XIANG_RE = re.compile(r"^(?P<no>\d+)[）)](?P<rest>.*)$")
_PAGE_NO_RE = re.compile(r"\s\d+\s*$")
_SCOPE_RE = re.compile(r"^\s*(?:本规范|本标准|本文件)?\s*不?适用(?:于|范围)")
_IMAGE_MD_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<path>[^)]+)\)")
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_IMG_ATTR_RE = re.compile(r'(?P<name>src|alt)\s*=\s*"(?P<value>[^"]*)"', re.IGNORECASE)

_CJK_CLASS = "[\u3400-\u4dbf\u4e00-\u9fff]"
_CJK_SPACE_RE = re.compile(rf"(?<={_CJK_CLASS})\s+(?={_CJK_CLASS})")


def normalize_title(text: str) -> str:
    """去掉匀字排版在汉字之间留下的空格，保留非汉字间的空格。"""
    title = text.strip()
    while True:
        updated = _CJK_SPACE_RE.sub("", title)
        if updated == title:
            return title
        title = updated


def parse_file(path: Path, standard: Standard) -> ParsedStandard:
    """解析一部规范文件；不改写源文件。"""
    return parse_text(path.read_text(encoding="utf-8"), standard, source_name=path.name)


def parse_text(text: str, standard: Standard, source_name: str = "") -> ParsedStandard:
    """解析规范全文，返回结构化的 ParsedStandard。"""
    lines = text.splitlines()
    issues: list[ParseIssue] = []
    front_matter, body_start = _split_front_matter(lines, issues)

    chapter_builders: list[_ChapterBuilder] = []
    section_builders: list[_SectionBuilder] = []
    clause_builders: list[_ClauseBuilder] = []
    table_builders: list[_TableBuilder] = []
    scope_blocks: list[ScopeBlock] = []
    images: list[ImagePlaceholder] = []

    current_chapter: _ChapterBuilder | None = None
    current_section: _SectionBuilder | None = None
    clause: _ClauseBuilder | None = None
    pending_caption: tuple[tables.Caption, str] | None = None
    note_parts: list[str] | None = None
    scope_parts: list[str] | None = None
    scope_line = 0
    scope_section: str | None = None

    def close_clause() -> None:
        nonlocal clause
        if clause is not None:
            clause_builders.append(clause)
            clause = None

    def close_scope() -> None:
        nonlocal scope_parts
        if scope_parts is not None:
            scope_blocks.append(
                ScopeBlock(
                    text=_join(scope_parts),
                    source_line=scope_line,
                    section_id=scope_section,
                )
            )
            scope_parts = None

    def flush_notes() -> None:
        nonlocal note_parts
        if note_parts is not None:
            if table_builders:
                table_builders[-1].notes.append(latex.restore(_join(note_parts)))
            note_parts = None

    for index in range(body_start, len(lines)):
        raw = lines[index]
        line_no = index + 1
        if not raw.strip():
            flush_notes()
            close_scope()
            continue

        marks, content = _split_heading(raw)
        clause_match = _CLAUSE_RE.match(content)
        section_match = _SECTION_RE.match(content) if marks else None
        chapter_match = _CHAPTER_RE.match(content) if marks else None
        caption = None if marks else tables.parse_caption(content)
        is_table_line = "<table" in raw.lower()
        structural = any((clause_match, section_match, chapter_match, caption, is_table_line))

        if scope_parts is not None and not structural:
            scope_parts.append(content)
            continue
        if scope_parts is not None:
            close_scope()

        if note_parts is not None:
            if not structural:
                note_parts.append(content)
                continue
            flush_notes()

        if chapter_match is not None:
            close_clause()
            raw_title = chapter_match.group("rest").strip()
            current_chapter = _ChapterBuilder(
                chapter_no=int(chapter_match.group("a")),
                raw_title=raw_title,
                title=normalize_title(raw_title),
                marks=marks,
                source_line=line_no,
            )
            chapter_builders.append(current_chapter)
            current_section = None
            continue

        if section_match is not None:
            close_clause()
            raw_title = section_match.group("rest").strip()
            title = normalize_title(raw_title)
            section_id = f"{section_match.group('a')}.{section_match.group('b')}"
            current_section = _SectionBuilder(
                section_id=section_id,
                chapter_no=int(section_match.group("a")),
                raw_title=raw_title,
                title=title,
                marks=marks,
                source_line=line_no,
                is_term="术语" in title,
            )
            section_builders.append(current_section)
            continue

        if clause_match is not None:
            close_clause()
            if marks:
                issues.append(
                    ParseIssue(
                        DefectKind.CLAUSE_MARKED_AS_HEADING,
                        line_no,
                        f"条文 {clause_match.group(0).split()[0]} 被标为标题",
                    )
                )
            chapter_no = (
                current_chapter.chapter_no
                if current_chapter is not None
                else int(clause_match.group("a"))
            )
            section_id = (
                current_section.section_id
                if current_section is not None
                else str(chapter_no)
            )
            path = tuple(
                item.title
                for item in (current_chapter, current_section)
                if item is not None
            )
            clause_no = ".".join(
                (clause_match.group("a"), clause_match.group("b"), clause_match.group("c"))
            )
            clause = _ClauseBuilder(
                clause_no=clause_no,
                num_key=(
                    int(clause_match.group("a")),
                    int(clause_match.group("b")),
                    int(clause_match.group("c")),
                ),
                chapter_no=chapter_no,
                section_id=section_id,
                path=path,
                source_line=line_no,
                end_line=line_no,
            )
            rest = clause_match.group("rest").strip()
            if rest:
                clause.intro_parts.append(rest)
            continue

        if caption is not None:
            pending_caption = (caption, latex.restore(content))
            continue

        if is_table_line:
            rows = tuple(
                tuple(latex.restore(cell) for cell in row)
                for row in tables.parse_html_table(raw)
            )
            caption_obj, caption_line = pending_caption if pending_caption else (None, "")
            table_id = caption_obj.table_id if caption_obj is not None else ""
            table_builders.append(
                _TableBuilder(
                    table_id=table_id,
                    caption=caption_line,
                    rows=rows,
                    source_line=line_no,
                    is_continuation=bool(caption_obj and caption_obj.is_continuation),
                    clause_no=tables.table_clause_no(table_id) if table_id else None,
                )
            )
            pending_caption = None
            continue

        if tables.is_note_line(content):
            if table_builders:
                note_parts = [content]
            continue

        previous_blank = index == body_start or not lines[index - 1].strip()
        if previous_blank and scope_parts is None and _SCOPE_RE.match(content):
            scope_parts = [content]
            scope_line = line_no
            if current_section is not None:
                scope_section = current_section.section_id
            elif current_chapter is not None:
                scope_section = str(current_chapter.chapter_no)
            else:
                scope_section = None
            continue

        placeholders = _extract_images(raw, line_no)
        if placeholders:
            images.extend(placeholders)
            if clause is not None:
                clause.images.extend(placeholders)
                if _strip_images(content).strip():
                    clause.add_line(content, line_no)
            continue

        if clause is None:
            continue
        kuan_match = _KUAN_RE.match(content)
        if kuan_match is not None:
            clause.start_kuan(int(kuan_match.group("no")), kuan_match.group("rest"), line_no)
            continue
        xiang_match = _XIANG_RE.match(content)
        if xiang_match is not None and clause.kuans:
            clause.start_item(int(xiang_match.group("no")), xiang_match.group("rest"), line_no)
            continue
        clause.add_line(content, line_no)

    close_clause()
    close_scope()
    flush_notes()

    chapter_levels = {len(item.marks) for item in chapter_builders}
    section_levels = {len(item.marks) for item in section_builders}
    if len(chapter_levels) > 1:
        distribution = "、".join(
            f"{'#' * level}×{sum(1 for item in chapter_builders if len(item.marks) == level)}"
            for level in sorted(chapter_levels)
        )
        issues.append(
            ParseIssue(
                DefectKind.CHAPTER_MARK_MIXED,
                None,
                f"章标题标记混用：{distribution}",
            )
        )
    if chapter_builders and section_builders and len(chapter_levels | section_levels) == 1:
        same_marks = "#" * next(iter(chapter_levels))
        issues.append(
            ParseIssue(
                DefectKind.CHAPTER_SECTION_SAME_LEVEL,
                None,
                f"章与节标题标记同为 {same_marks}",
            )
        )

    table_models = tuple(
        Table(
            table_id=builder.table_id,
            caption=builder.caption,
            rows=builder.rows,
            notes=tuple(builder.notes),
            source_line=builder.source_line,
            is_continuation=builder.is_continuation,
            clause_no=builder.clause_no,
        )
        for builder in table_builders
    )
    tables_by_clause: dict[str, list[Table]] = {}
    for table in table_models:
        if table.clause_no:
            tables_by_clause.setdefault(table.clause_no, []).append(table)

    clause_models = tuple(
        _build_clause(builder, standard, tuple(tables_by_clause.get(builder.clause_no, ())))
        for builder in clause_builders
    )
    section_models = tuple(
        Section(
            section_id=builder.section_id,
            chapter_no=builder.chapter_no,
            title=builder.title,
            raw_title=builder.raw_title,
            marks=builder.marks,
            source_line=builder.source_line,
            is_term=builder.is_term,
        )
        for builder in section_builders
    )
    chapter_models = tuple(
        Chapter(
            chapter_no=builder.chapter_no,
            title=builder.title,
            raw_title=builder.raw_title,
            marks=builder.marks,
            source_line=builder.source_line,
        )
        for builder in chapter_builders
    )
    section_by_id = {section.section_id: section for section in section_models}
    terms: list[Term] = []
    for model in clause_models:
        section = section_by_id.get(model.section_id)
        if section is None or not section.is_term:
            continue
        name, definition = _split_term(model.text)
        terms.append(
            Term(
                name=name,
                definition=definition,
                clause_id=model.clause_id,
                section_id=model.section_id,
                source_line=model.source_line,
            )
        )

    return ParsedStandard(
        standard=standard,
        source_name=source_name,
        chapters=chapter_models,
        sections=section_models,
        clauses=clause_models,
        tables=table_models,
        front_matter=front_matter,
        scopes=tuple(scope_blocks),
        terms=tuple(terms),
        images=tuple(images),
        latex_occurrences=latex.extract(text),
        symbol_candidates=latex.candidates(text),
        issues=tuple(issues),
    )


def _split_heading(line: str) -> tuple[str, str]:
    """返回 (mark 序列, 去标记文本)；不是标题行时 mark 为空串。"""
    stripped = line.strip()
    match = _HEADING_RE.match(stripped)
    if match is not None and match.group("text").strip():
        return match.group("marks"), match.group("text").strip()
    return "", stripped


def _find_heading(lines: list[str], title: str) -> int | None:
    for index, line in enumerate(lines):
        marks, text = _split_heading(line)
        if marks and normalize_title(text) == title:
            return index
    return None


def _first_body_line(lines: list[str], start: int, issues: list[ParseIssue]) -> int:
    """正文起点：第一个不带页码的章/节标题行；区间内的带标记条目记为缺陷。"""
    for index in range(start, len(lines)):
        marks, text = _split_heading(lines[index])
        if not marks:
            continue
        if _PAGE_NO_RE.search(text):
            issues.append(
                ParseIssue(
                    DefectKind.TOC_ENTRY_MARKED,
                    index + 1,
                    "目次条目带标题标记，已排除出正文",
                )
            )
            continue
        if _CLAUSE_RE.match(text) or _SECTION_RE.match(text) or _CHAPTER_RE.match(text):
            return index
    return len(lines)


def _split_front_matter(
    lines: list[str], issues: list[ParseIssue]
) -> tuple[tuple[FrontMatter, ...], int]:
    preface_index = _find_heading(lines, _PREFACE_TITLE)
    toc_index = _find_heading(lines, _TOC_TITLE)
    if toc_index is not None:
        body_start = _first_body_line(lines, toc_index + 1, issues)
    elif preface_index is not None:
        body_start = _first_body_line(lines, preface_index + 1, issues)
    else:
        body_start = _first_body_line(lines, 0, issues)

    blocks: list[FrontMatter] = []
    if preface_index is not None:
        end = toc_index if toc_index is not None and toc_index > preface_index else body_start
        blocks.append(
            FrontMatter(
                kind=_PREFACE_TITLE,
                text="\n".join(lines[preface_index:end]).strip(),
                source_line=preface_index + 1,
                end_line=end,
            )
        )
    if toc_index is not None:
        blocks.append(
            FrontMatter(
                kind=_TOC_TITLE,
                text="\n".join(lines[toc_index:body_start]).strip(),
                source_line=toc_index + 1,
                end_line=body_start,
            )
        )
    return tuple(blocks), body_start


def _extract_images(raw: str, line_no: int) -> list[ImagePlaceholder]:
    result: list[ImagePlaceholder] = []
    for match in _IMAGE_MD_RE.finditer(raw):
        result.append(
            ImagePlaceholder(
                alt=match.group("alt"),
                path=match.group("path"),
                source_line=line_no,
            )
        )
    for tag in _IMG_TAG_RE.finditer(raw):
        attributes = {
            item.group("name").lower(): item.group("value")
            for item in _IMG_ATTR_RE.finditer(tag.group(0))
        }
        result.append(
            ImagePlaceholder(
                alt=attributes.get("alt", ""),
                path=attributes.get("src", ""),
                source_line=line_no,
            )
        )
    return result


def _strip_images(text: str) -> str:
    return _IMG_TAG_RE.sub("", _IMAGE_MD_RE.sub("", text))


def _split_term(text: str) -> tuple[str, str]:
    for separator in ("：", ":"):
        if separator in text:
            name, _, definition = text.partition(separator)
            return name.strip(), definition.strip()
    return "", text.strip()


def _join(parts: list[str]) -> str:
    """拼接被 PDF 转换拆开的行；中文行间不加分隔符。"""
    return "".join(part.strip() for part in parts if part.strip())


def _clause_text(intro: str, kuans: tuple[Kuan, ...]) -> str:
    lines: list[str] = []
    if intro:
        lines.append(intro)
    for kuan in kuans:
        pieces = [kuan.text] if kuan.text else []
        pieces.extend(f"{item.item_no}）{item.text}" for item in kuan.items)
        kuan_line = " ".join(piece for piece in pieces if piece)
        if kuan_line:
            lines.append(f"{kuan.kuan_no} {kuan_line}")
    return "\n".join(lines)


def _build_clause(
    builder: _ClauseBuilder, standard: Standard, table_models: tuple[Table, ...]
) -> Clause:
    kuans = tuple(
        Kuan(
            kuan_no=kuan.kuan_no,
            text=latex.restore(_join(kuan.parts)),
            items=tuple(
                Xiang(
                    item_no=item.item_no,
                    text=latex.restore(_join(item.parts)),
                    source_line=item.source_line,
                )
                for item in kuan.items
            ),
            source_line=kuan.source_line,
        )
        for kuan in builder.kuans
    )
    intro = latex.restore(_join(builder.intro_parts))
    return Clause(
        clause_id=f"{standard.standard_id}_{builder.clause_no}",
        clause_no=builder.clause_no,
        num_key=builder.num_key,
        chapter_no=builder.chapter_no,
        section_id=builder.section_id,
        path=builder.path,
        text=latex.restore(_clause_text(intro, kuans)),
        intro=intro,
        kuans=kuans,
        tables=table_models,
        images=tuple(builder.images),
        source_line=builder.source_line,
        end_line=builder.end_line,
    )


@dataclass
class _XiangBuilder:
    item_no: int
    source_line: int
    parts: list[str] = field(default_factory=list)


@dataclass
class _KuanBuilder:
    kuan_no: int
    source_line: int
    parts: list[str] = field(default_factory=list)
    items: list[_XiangBuilder] = field(default_factory=list)


@dataclass
class _ChapterBuilder:
    chapter_no: int
    raw_title: str
    title: str
    marks: str
    source_line: int


@dataclass
class _SectionBuilder:
    section_id: str
    chapter_no: int
    raw_title: str
    title: str
    marks: str
    source_line: int
    is_term: bool


@dataclass
class _TableBuilder:
    table_id: str
    caption: str
    rows: tuple[tuple[str, ...], ...]
    source_line: int
    is_continuation: bool
    clause_no: str | None
    notes: list[str] = field(default_factory=list)


@dataclass
class _ClauseBuilder:
    clause_no: str
    num_key: tuple[int, int, int]
    chapter_no: int
    section_id: str
    path: tuple[str, ...]
    source_line: int
    end_line: int
    intro_parts: list[str] = field(default_factory=list)
    kuans: list[_KuanBuilder] = field(default_factory=list)
    images: list[ImagePlaceholder] = field(default_factory=list)

    def add_line(self, text: str, line_no: int) -> None:
        self.end_line = max(self.end_line, line_no)
        if not self.kuans:
            self.intro_parts.append(text)
            return
        kuan = self.kuans[-1]
        if kuan.items:
            kuan.items[-1].parts.append(text)
        else:
            kuan.parts.append(text)

    def start_kuan(self, kuan_no: int, text: str, line_no: int) -> None:
        self.end_line = max(self.end_line, line_no)
        self.kuans.append(_KuanBuilder(kuan_no=kuan_no, source_line=line_no, parts=[text]))

    def start_item(self, item_no: int, text: str, line_no: int) -> None:
        self.end_line = max(self.end_line, line_no)
        self.kuans[-1].items.append(
            _XiangBuilder(item_no=item_no, source_line=line_no, parts=[text])
        )
