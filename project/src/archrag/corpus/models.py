"""语料层的共享数据契约（叶子模块，不反向依赖解析器与存储层）。

数据流：Standard → Chapter/Section → Clause（含款、项）→ Table/图片占位，
以及不参与检索的 FrontMatter 与仅作条件限定的 ScopeBlock。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

NumberKey = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class Standard:
    """一部规范的标准号、全称与来源文件。"""

    standard_id: str
    name: str
    file_name: str
    effective_date: date | None = None
    mandatory: bool = True


@dataclass(frozen=True, slots=True)
class Xiang:
    """项：款下的编号条目，不单独成块。"""

    item_no: int
    text: str
    source_line: int


@dataclass(frozen=True, slots=True)
class Kuan:
    """款：条内的编号段落；项依附于所属款。"""

    kuan_no: int
    text: str
    items: tuple[Xiang, ...] = ()
    source_line: int = 0


@dataclass(frozen=True, slots=True)
class ImagePlaceholder:
    """图片语法占位：只保留 alt 与路径，不解析内容。"""

    alt: str
    path: str
    source_line: int


@dataclass(frozen=True, slots=True)
class Table:
    """HTML 表格：rows 已按 colspan/rowspan 展开，文本已完成 LaTeX 还原。"""

    table_id: str
    caption: str
    rows: tuple[tuple[str, ...], ...]
    notes: tuple[str, ...] = ()
    source_line: int = 0
    is_continuation: bool = False
    clause_no: str | None = None


@dataclass(frozen=True, slots=True)
class Chapter:
    """章。title 为内存归一化结果，raw_title 保留源文件原样。"""

    chapter_no: int
    title: str
    raw_title: str
    marks: str
    source_line: int


@dataclass(frozen=True, slots=True)
class Section:
    """节；章下无节时由 Clause.section_id 退化为章号。"""

    section_id: str
    chapter_no: int
    title: str
    raw_title: str
    marks: str
    source_line: int
    is_term: bool = False


@dataclass(frozen=True, slots=True)
class Clause:
    """条：检索与引用的主粒度，text 不含其引用的表格内容。"""

    clause_id: str
    clause_no: str
    num_key: NumberKey
    chapter_no: int
    section_id: str
    path: tuple[str, ...]
    text: str
    intro: str
    kuans: tuple[Kuan, ...]
    tables: tuple[Table, ...]
    images: tuple[ImagePlaceholder, ...]
    source_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class FrontMatter:
    """前言与目次：入库留存但不参与检索。"""

    kind: str
    text: str
    source_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class ScopeBlock:
    """适用范围说明：可被检索，但只能作条件限定，不得作为答案依据。"""

    text: str
    source_line: int
    section_id: str | None = None
    clause_id: str | None = None


@dataclass(frozen=True, slots=True)
class Term:
    """术语章条目：属规范正文，可作为答案依据。"""

    name: str
    definition: str
    clause_id: str
    section_id: str
    source_line: int


@dataclass(frozen=True, slots=True)
class LatexOccurrence:
    """一处行内 LaTeX；restored 为可读文本，真公式保留原文。"""

    raw: str
    restored: str
    start: int
    end: int
    is_formula: bool


@dataclass(frozen=True, slots=True)
class SymbolCandidate:
    """符号 → 中文术语候选，供人工审核后写入查询扩展表。"""

    symbol: str
    term: str | None
    context: str


class DefectKind(StrEnum):
    """转换工具四类已知缺陷，逐行分类。"""

    CHAPTER_MARK_MIXED = "章标记混用"
    CHAPTER_SECTION_SAME_LEVEL = "章与节全同级"
    TOC_ENTRY_MARKED = "目次条目带标记"
    CLAUSE_MARKED_AS_HEADING = "条文被标为标题"


class ChunkType(StrEnum):
    """检索块类型；scope 可检索但不得作为答案依据。"""

    BODY = "body"
    TERM = "term"
    SCOPE = "scope"
    TABLE_ROW = "table_row"


class RefType(StrEnum):
    """引用边类型；跨标准引用单独成边。"""

    TABLE = "table"
    CLAUSE = "clause"
    STANDARD = "standard"


@dataclass(frozen=True, slots=True)
class Chunk:
    """检索块：text 为正文，embed_text 为实际嵌入/重排文本。"""

    chunk_id: str
    chunk_type: ChunkType
    standard_id: str
    standard_name: str
    level: str
    version: str
    source_file: str
    clause_id: str | None
    clause_no: str | None
    chapter_no: int | None
    section_id: str | None
    section_num: tuple[int, int] | None
    num_key: NumberKey | None
    path: tuple[str, ...]
    kuan_no: int | None
    item_nos: tuple[int, ...]
    section_clause_count: int
    table_id: str | None
    row_no: int | None
    has_table: bool
    text: str
    embed_text: str
    token_count: int
    over_limit_reason: str | None = None


@dataclass(frozen=True, slots=True)
class Reference:
    """条 → 表 / 条 / 标准 的引用边。"""

    src_clause_id: str
    ref_type: RefType
    dst_id: str
    dst_standard_id: str | None
    source_line: int | None = None


@dataclass(frozen=True, slots=True)
class Alias:
    """标准别名种子：标准号、全称、简称。"""

    standard_id: str
    alias: str
    alias_type: str


@dataclass(frozen=True, slots=True)
class LexiconTerm:
    """术语候选（人工审核前不入正式检索用词典）。"""

    term: str
    freq: int
    score: float
    source: str


@dataclass(frozen=True, slots=True)
class Expansion:
    """查询扩展候选：符号→中文、表格条件词等。"""

    from_text: str
    to_text: str
    kind: str


@dataclass(frozen=True, slots=True)
class ParseIssue:
    """解析期间记录的缺陷；line 为 None 表示文件级结论。"""

    kind: DefectKind
    line: int | None
    detail: str


@dataclass(frozen=True, slots=True)
class ParsedStandard:
    """一部规范的完整解析结果。"""

    standard: Standard
    source_name: str
    chapters: tuple[Chapter, ...]
    sections: tuple[Section, ...]
    clauses: tuple[Clause, ...]
    tables: tuple[Table, ...]
    front_matter: tuple[FrontMatter, ...]
    scopes: tuple[ScopeBlock, ...]
    terms: tuple[Term, ...]
    images: tuple[ImagePlaceholder, ...]
    latex_occurrences: tuple[LatexOccurrence, ...]
    symbol_candidates: tuple[SymbolCandidate, ...]
    issues: tuple[ParseIssue, ...]

    def clause_by_no(self, clause_no: str) -> Clause | None:
        """按条号取条；条号在一个标准内唯一。"""
        for clause in self.clauses:
            if clause.clause_no == clause_no:
                return clause
        return None

    def clause_gaps(self) -> tuple[tuple[str, str], ...]:
        """条号连续性缺口；放行两类跨章过渡（见 level-rules）。"""
        gaps: list[tuple[str, str]] = []
        for previous, current in zip(self.clauses, self.clauses[1:], strict=False):
            a, b, c = previous.num_key
            next_a, next_b, next_c = current.num_key
            if (a, b) == (next_a, next_b):
                ok = next_c == c + 1
            elif (a == next_a and b + 1 == next_b) or next_a == a + 1:
                ok = next_c == 1
            else:
                ok = False
            if not ok:
                gaps.append((previous.clause_no, current.clause_no))
        return tuple(gaps)

    def kuan_count(self) -> int:
        return sum(len(clause.kuans) for clause in self.clauses)

    def xiang_count(self) -> int:
        return sum(len(kuan.items) for clause in self.clauses for kuan in clause.kuans)
