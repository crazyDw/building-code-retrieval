"""切块：256 token 硬上限，超限才按款/项切，产出四类检索块。

长度口径：块文本 = 「标准名 + 章节路径 + 条号 +（款号）+ 正文」（表格行块
为「标准名 + 表名 + 表题 + 表格注 + 行内容」），按 bge-m3 tokenizer 计量；
条文引用的表格内容不计入条文块长度（铁律 11）。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from archrag.corpus.models import (
    Chunk,
    ChunkType,
    Clause,
    Kuan,
    ParsedStandard,
    ScopeBlock,
    Section,
    Table,
)
from archrag.errors import ChunkError

DEFAULT_MAX_TOKENS = 256

_VALUE_CELL_RE = re.compile(r"^\s*(?:[≤≥<>]=?)?\s*-?\d+(?:\.\d+)?\s*$")
_SENTENCE_RE = re.compile(r"[^。；;！？!?]+[。；;！？!?]?")
_CAPTION_PREFIX_RE = re.compile(r"^\s*续?表\s*\d+(?:\.\d+){2}(?:-\d+)?\s*")


@dataclass(frozen=True, slots=True)
class _Context:
    standard_id: str
    standard_name: str
    level: str
    version: str
    source_file: str
    max_tokens: int
    count_tokens: Callable[[str], int]
    section_clause_counts: dict[str, int]
    sections: dict[str, Section]
    clauses_by_no: dict[str, Clause]


def build_chunks(
    parsed: ParsedStandard,
    *,
    version: str,
    count_tokens: Callable[[str], int],
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> tuple[Chunk, ...]:
    """把一部规范切成确定性、可重建的检索块。"""
    context = _Context(
        standard_id=parsed.standard.standard_id,
        standard_name=parsed.standard.name,
        level="全文强制" if parsed.standard.mandatory else "非全文强制",
        version=version,
        source_file=parsed.source_name,
        max_tokens=max_tokens,
        count_tokens=count_tokens,
        section_clause_counts=_section_clause_counts(parsed),
        sections={section.section_id: section for section in parsed.sections},
        clauses_by_no={clause.clause_no: clause for clause in parsed.clauses},
    )
    chunks: list[Chunk] = []
    table_rows: dict[int, list[Chunk]] = {}
    for table in parsed.tables:
        table_rows[table.source_line] = _table_row_chunks(context, table)
    for clause in parsed.clauses:
        chunks.extend(_clause_chunks(context, clause))
        for table in clause.tables:
            chunks.extend(table_rows.get(table.source_line, ()))
    for table in parsed.tables:
        if table.clause_no is None:
            chunks.extend(table_rows.get(table.source_line, ()))
    chunks.extend(_scope_chunks(context, parsed.scopes))
    validate_chunks(tuple(chunks), max_tokens=max_tokens)
    return tuple(chunks)


def validate_chunks(
    chunks: Sequence[Chunk], *, max_tokens: int = DEFAULT_MAX_TOKENS
) -> tuple[Chunk, ...]:
    """校验块长与 ID 唯一性，返回允许超限的例外块。"""
    identifiers = [chunk.chunk_id for chunk in chunks]
    if len(set(identifiers)) != len(identifiers):
        duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
        raise ChunkError(f"chunk_id 重复：{duplicates[:5]}")
    over_limit = tuple(chunk for chunk in chunks if chunk.token_count > max_tokens)
    unflagged = [chunk for chunk in over_limit if not chunk.over_limit_reason]
    if unflagged:
        details = ", ".join(f"{chunk.chunk_id}={chunk.token_count}" for chunk in unflagged[:5])
        raise ChunkError(f"存在未标记的超限块：{details}")
    return over_limit


def render_clause(clause: Clause) -> str:
    """整条文本：引导句 + 各款（含项）。"""
    parts = [clause.intro] if clause.intro else []
    parts.extend(render_kuan(kuan) for kuan in clause.kuans)
    return "\n".join(part for part in parts if part)


def render_kuan(kuan: Kuan) -> str:
    """款文本：款引导句 + 完整项。"""
    pieces = [f"{kuan.kuan_no} {kuan.text}".strip()]
    pieces.extend(f"{item.item_no}）{item.text}" for item in kuan.items)
    return "\n".join(piece for piece in pieces if piece)


def _section_clause_counts(parsed: ParsedStandard) -> dict[str, int]:
    counts: dict[str, int] = {}
    for clause in parsed.clauses:
        counts[clause.section_id] = counts.get(clause.section_id, 0) + 1
    return counts


def _clause_chunks(context: _Context, clause: Clause) -> list[Chunk]:
    section = context.sections.get(clause.section_id)
    is_term = bool(section and section.is_term)
    chunk_type = ChunkType.TERM if is_term else ChunkType.BODY
    kind = chunk_type.value
    whole = render_clause(clause)
    if _fits(context, _body_prefix(context, clause, None), whole):
        return [
            _make_body(
                context,
                clause,
                chunk_type,
                chunk_id=f"{clause.clause_id}::{kind}",
                text=whole,
            )
        ]
    if not clause.kuans:
        return [
            _make_body(
                context,
                clause,
                chunk_type,
                chunk_id=f"{clause.clause_id}::{kind}:s{index}",
                text=text,
                over_limit_reason=reason,
            )
            for index, (text, reason) in enumerate(
                _pack_text(context, _body_prefix(context, clause, None), whole), start=1
            )
        ]
    chunks: list[Chunk] = []
    if clause.intro:
        for index, (text, reason) in enumerate(
            _pack_text(context, _body_prefix(context, clause, None), clause.intro), start=1
        ):
            suffix = "intro" if index == 1 else f"intro:{index}"
            chunks.append(
                _make_body(
                    context,
                    clause,
                    chunk_type,
                    chunk_id=f"{clause.clause_id}::{kind}:{suffix}",
                    text=text,
                    over_limit_reason=reason,
                )
            )
    for kuan in clause.kuans:
        chunks.extend(_kuan_chunks(context, clause, chunk_type, kuan))
    return chunks


def _kuan_chunks(
    context: _Context, clause: Clause, chunk_type: ChunkType, kuan: Kuan
) -> list[Chunk]:
    kind = chunk_type.value
    prefix = _body_prefix(context, clause, kuan.kuan_no)
    text = render_kuan(kuan)
    if _fits(context, prefix, text):
        return [
            _make_body(
                context,
                clause,
                chunk_type,
                chunk_id=f"{clause.clause_id}::{kind}:k{kuan.kuan_no}",
                text=text,
                kuan_no=kuan.kuan_no,
                item_nos=tuple(item.item_no for item in kuan.items),
            )
        ]
    if not kuan.items:
        return [
            _make_body(
                context,
                clause,
                chunk_type,
                chunk_id=f"{clause.clause_id}::{kind}:k{kuan.kuan_no}:s{index}",
                text=part_text,
                kuan_no=kuan.kuan_no,
                over_limit_reason=reason,
            )
            for index, (part_text, reason) in enumerate(
                _pack_text(context, prefix, f"{kuan.kuan_no} {kuan.text}".strip()), start=1
            )
        ]
    parts: list[Chunk] = []
    for index, (part_text, item_nos, reason) in enumerate(
        _pack_items(context, prefix, kuan), start=1
    ):
        parts.append(
            _make_body(
                context,
                clause,
                chunk_type,
                chunk_id=f"{clause.clause_id}::{kind}:k{kuan.kuan_no}:p{index}",
                text=part_text,
                kuan_no=kuan.kuan_no,
                item_nos=item_nos,
                over_limit_reason=reason,
            )
        )
    return parts


def _pack_items(
    context: _Context, prefix: str, kuan: Kuan
) -> list[tuple[str, tuple[int, ...], str | None]]:
    """把款的项按边界打包；只在「单个项自身超限」时允许超限。"""
    lead = f"{kuan.kuan_no} {kuan.text}".strip()

    def compose(items: list) -> str:
        return "\n".join([lead] + [f"{item.item_no}）{item.text}" for item in items])

    parts: list[tuple[str, tuple[int, ...], str | None]] = []
    current: list = []
    for item in kuan.items:
        if current and not _fits(context, prefix, compose([*current, item])):
            parts.append((compose(current), tuple(entry.item_no for entry in current), None))
            current = []
        current.append(item)
        if not _fits(context, prefix, compose(current)):
            parts.append(
                (
                    compose(current),
                    tuple(entry.item_no for entry in current),
                    "单个项自身超限",
                )
            )
            current = []
    if current:
        parts.append((compose(current), tuple(entry.item_no for entry in current), None))
    return parts


def _pack_text(
    context: _Context, prefix: str, text: str
) -> list[tuple[str, str | None]]:
    """按句边界打包；单句超限时保留并标记（无款可切）。"""
    sentences = [sentence.strip() for sentence in _SENTENCE_RE.findall(text) if sentence.strip()]
    if not sentences:
        sentences = [text.strip()]
    parts: list[tuple[str, str | None]] = []
    current: list[str] = []
    for sentence in sentences:
        if current and not _fits(context, prefix, "".join([*current, sentence])):
            parts.append(("".join(current), None))
            current = []
        current.append(sentence)
        if not _fits(context, prefix, "".join(current)):
            parts.append(("".join(current), "单句超限"))
            current = []
    if current:
        parts.append(("".join(current), None))
    return parts


def _table_row_chunks(context: _Context, table: Table) -> list[Chunk]:
    if not table.rows:
        return []
    header_count = _header_row_count(table.rows)
    header_rows = table.rows[:header_count]
    columns = _column_names(header_rows)
    prefix = _table_prefix(context, table)
    owner = context.clauses_by_no.get(table.clause_no or "")
    chunks: list[Chunk] = []
    for offset, row in enumerate(table.rows[header_count:]):
        row_no = header_count + offset + 1
        sentence = _row_sentence(columns, row)
        if not sentence:
            continue
        chunks.append(
            _make(
                context,
                chunk_id=f"{context.standard_id}::table:{table.source_line}:r{row_no}",
                chunk_type=ChunkType.TABLE_ROW,
                text=sentence,
                embed_prefix=prefix,
                clause_no=table.clause_no,
                clause_id=owner.clause_id if owner else None,
                table_id=table.table_id,
                row_no=row_no,
                section_id=owner.section_id if owner else None,
                chapter_no=owner.chapter_no if owner else None,
                num_key=owner.num_key if owner else None,
                path=owner.path if owner else (),
                has_table=True,
                over_limit_reason=(
                    "表格行超限（不可切）"
                    if not _fits(context, prefix, sentence)
                    else None
                ),
            )
        )
    return chunks


def _scope_chunks(context: _Context, scopes: Sequence[ScopeBlock]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for scope in scopes:
        prefix = " ".join(
            part for part in (context.standard_name, scope.section_id or "") if part
        )
        chunks.append(
            _make(
                context,
                chunk_id=f"{context.standard_id}::scope:{scope.source_line}",
                chunk_type=ChunkType.SCOPE,
                text=scope.text,
                embed_prefix=prefix,
                clause_id=scope.clause_id,
                section_id=scope.section_id,
                over_limit_reason=(
                    "范围说明超限（不可作答案依据，保留整块）"
                    if not _fits(context, prefix, scope.text)
                    else None
                ),
            )
        )
    return chunks


def _header_row_count(rows: tuple[tuple[str, ...], ...]) -> int:
    """表头行数：从第 2 行起找到第一个含纯数字单元格的行。"""
    for index, row in enumerate(rows[1:], start=1):
        if any(_VALUE_CELL_RE.match(cell) for cell in row):
            return min(index, 3)
    return 1


def _column_names(header_rows: tuple[tuple[str, ...], ...]) -> tuple[str, ...]:
    if not header_rows:
        return ()
    width = max(len(row) for row in header_rows)
    names: list[str] = []
    for column in range(width):
        values: list[str] = []
        for row in header_rows:
            value = row[column].strip() if column < len(row) else ""
            if value and value not in values:
                values.append(value)
        names.append(" / ".join(values) if values else f"列{column + 1}")
    return tuple(names)


def _row_sentence(columns: tuple[str, ...], row: tuple[str, ...]) -> str:
    pieces: list[str] = []
    seen: set[tuple[str, str]] = set()
    for index, value in enumerate(row):
        text = value.strip()
        if not text:
            continue
        label = columns[index].strip() if index < len(columns) else ""
        if (label, text) in seen:
            continue
        seen.add((label, text))
        if label and label != text:
            pieces.append(f"{label}为{text}")
        else:
            pieces.append(text)
    return "；".join(pieces)


def _caption_title(table: Table) -> str:
    return _CAPTION_PREFIX_RE.sub("", table.caption).strip()


def _table_prefix(context: _Context, table: Table) -> str:
    pieces = [context.standard_name, table.table_id]
    title = _caption_title(table)
    if title:
        pieces.append(title)
    if table.notes:
        pieces.append("；".join(table.notes))
    return " ".join(piece for piece in pieces if piece)


def _body_prefix(context: _Context, clause: Clause, kuan_no: int | None) -> str:
    pieces = [context.standard_name]
    if clause.path:
        pieces.append(" › ".join(clause.path))
    pieces.append(clause.clause_no)
    if kuan_no is not None:
        pieces.append(f"款{kuan_no}")
    return " ".join(pieces)


def _compose(prefix: str, text: str) -> str:
    return f"{prefix} {text}".strip()


def _fits(context: _Context, prefix: str, text: str) -> bool:
    return context.count_tokens(_compose(prefix, text)) <= context.max_tokens


def _make_body(
    context: _Context,
    clause: Clause,
    chunk_type: ChunkType,
    *,
    chunk_id: str,
    text: str,
    kuan_no: int | None = None,
    item_nos: tuple[int, ...] = (),
    over_limit_reason: str | None = None,
) -> Chunk:
    return _make(
        context,
        chunk_id=chunk_id,
        chunk_type=chunk_type,
        text=text,
        embed_prefix=_body_prefix(context, clause, kuan_no),
        clause_no=clause.clause_no,
        clause_id=clause.clause_id,
        section_id=clause.section_id,
        chapter_no=clause.chapter_no,
        num_key=clause.num_key,
        path=clause.path,
        kuan_no=kuan_no,
        item_nos=item_nos,
        has_table=bool(clause.tables),
        over_limit_reason=over_limit_reason,
    )


def _make(
    context: _Context,
    *,
    chunk_id: str,
    chunk_type: ChunkType,
    text: str,
    embed_prefix: str,
    clause_no: str | None = None,
    clause_id: str | None = None,
    section_id: str | None = None,
    chapter_no: int | None = None,
    num_key: tuple[int, int, int] | None = None,
    path: tuple[str, ...] = (),
    kuan_no: int | None = None,
    item_nos: tuple[int, ...] = (),
    table_id: str | None = None,
    row_no: int | None = None,
    has_table: bool = False,
    over_limit_reason: str | None = None,
) -> Chunk:
    embed_text = _compose(embed_prefix, text)
    token_count = context.count_tokens(embed_text)
    section_num = None
    if section_id and "." in section_id:
        left, right = section_id.split(".", 1)
        if left.isdigit() and right.isdigit():
            section_num = (int(left), int(right))
    return Chunk(
        chunk_id=chunk_id,
        chunk_type=chunk_type,
        standard_id=context.standard_id,
        standard_name=context.standard_name,
        level=context.level,
        version=context.version,
        source_file=context.source_file,
        clause_id=clause_id,
        clause_no=clause_no,
        chapter_no=chapter_no,
        section_id=section_id,
        section_num=section_num,
        num_key=num_key,
        path=path,
        kuan_no=kuan_no,
        item_nos=item_nos,
        section_clause_count=context.section_clause_counts.get(section_id or "", 0),
        table_id=table_id,
        row_no=row_no,
        has_table=has_table,
        text=text,
        embed_text=embed_text,
        token_count=token_count,
        over_limit_reason=over_limit_reason,
    )
