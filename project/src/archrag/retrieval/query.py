"""查询理解：条款号短路 → 别名限定 → 数值剥离 → 按需改写 → 同义词追加。"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

_CLAUSE_QUERY_RE = re.compile(
    r"^\s*(?:(?P<standard>GB\s*\d{5}(?:-\d{4})?)\s*)?"
    r"(?:第\s*)?(?P<no>\d+\.\d+\.\d+)\s*条?\s*$"
)
_CLAUSE_MENTION_RE = re.compile(r"\d+\.\d+\.\d+")
_UNIT_PATTERN = (
    r"(?:平方米|立方米|m2|m3|㎡|层|米|千米|mm|cm|km|kg|MPa|kN|Pa|dB|lx|"
    r"m|N|t|%|度|℃|岁|人|辆|个|台|座|次|倍|年|天|h|min|s)?"
)
_NUMBER_RE = re.compile(rf"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])\s*(?P<unit>{_UNIT_PATTERN})")
_PRONOUN_RE = re.compile(
    r"(这个|那个|它|上述|前面|之前|还有呢|该(?:条|项目|建筑|规范|工程|构件|部位|问题|要求|做法|规定))"
)
_VAGUE_RE = re.compile(
    r"(有什么要求|需要注意|怎么做|如何|哪些要求|什么规定|有哪些规定|相关要求|大概|"
    r"要求是什么|有什么规定|该注意|注意什么|注意哪些)"
)
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
_NON_WORD_RE = re.compile(r"[^\u4e00-\u9fffA-Za-z0-9]+")


@dataclass(frozen=True, slots=True)
class NumberMention:
    """提问中抽出的数值条件。"""

    raw: str
    value: float
    unit: str | None


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """一轮查询的理解结果；检索只用 retrieval_text 编码一次。"""

    original: str
    retrieval_text: str
    clause_no: str | None
    clause_standard_id: str | None
    standard_scope: tuple[str, ...]
    numbers: tuple[NumberMention, ...]
    expanded_terms: tuple[str, ...]
    rewrite_needed: bool
    rewrite_used: bool
    is_broad: bool


def plan_query(
    text: str,
    *,
    alias_index: Mapping[str, str] | None = None,
    expansions: Sequence[tuple[str, str]] = (),
    rewriter: Callable[[str], str] | None = None,
) -> QueryPlan:
    """按固定顺序执行查询理解，条款号命中即短路。"""
    original = text.strip()
    clause_match = _CLAUSE_QUERY_RE.match(original)
    if clause_match is not None:
        return QueryPlan(
            original=original,
            retrieval_text=original,
            clause_no=clause_match.group("no"),
            clause_standard_id=_normalize_standard(clause_match.group("standard")),
            standard_scope=(),
            numbers=(),
            expanded_terms=(),
            rewrite_needed=False,
            rewrite_used=False,
            is_broad=False,
        )
    scope = match_standard_aliases(original, alias_index or {})
    numbers = extract_numbers(original)
    base = strip_numbers(original)
    rewrite_needed = needs_rewrite(base)
    rewrite_used = False
    if rewrite_needed and rewriter is not None:
        rewritten = rewriter(base).strip()
        if rewritten:
            base = rewritten
            rewrite_used = True
    expanded = expand_terms(base, expansions)
    retrieval_text = _tidy(f"{base} {' '.join(expanded)}" if expanded else base)
    return QueryPlan(
        original=original,
        retrieval_text=retrieval_text,
        clause_no=None,
        clause_standard_id=None,
        standard_scope=scope,
        numbers=numbers,
        expanded_terms=expanded,
        rewrite_needed=rewrite_needed,
        rewrite_used=rewrite_used,
        is_broad=is_broad_query(
            base,
            has_scope=bool(scope),
            has_terms=bool(expanded),
        ),
    )


def match_standard_aliases(text: str, alias_index: Mapping[str, str]) -> tuple[str, ...]:
    """完整别名匹配（汉字按整段相等，非汉字按词边界）；避免子串误判。"""
    cjk_runs = set(_CJK_RUN_RE.findall(text))
    found: list[str] = []
    for alias, standard_id in alias_index.items():
        matched = False
        if re.fullmatch(r"[\u4e00-\u9fff]+", alias):
            matched = alias in cjk_runs
        else:
            pattern = rf"(?<![\w-]){re.escape(alias)}(?![\w-])"
            matched = re.search(pattern, text, re.IGNORECASE) is not None
        if matched and standard_id not in found:
            found.append(standard_id)
    return tuple(found)


def extract_numbers(text: str) -> tuple[NumberMention, ...]:
    """抽取数值条件；属于条款号的点分数字不抽取。"""
    clause_spans = [match.span() for match in _CLAUSE_MENTION_RE.finditer(text)]
    mentions: list[NumberMention] = []
    for match in _NUMBER_RE.finditer(text):
        if any(start <= match.start() < end for start, end in clause_spans):
            continue
        unit = match.group("unit") or None
        mentions.append(
            NumberMention(
                raw=match.group(0).strip(),
                value=float(match.group(1)),
                unit=unit,
            )
        )
    return tuple(mentions)


def strip_numbers(text: str) -> str:
    """剥离数值后的场景描述，检索编码只用它。"""
    clause_spans = [match.span() for match in _CLAUSE_MENTION_RE.finditer(text)]

    def _replace(match: re.Match[str]) -> str:
        if any(start <= match.start() < end for start, end in clause_spans):
            return match.group(0)
        return " "

    return _tidy(_NUMBER_RE.sub(_replace, text))


def needs_rewrite(text: str) -> bool:
    """仅指代词或长度少于 10 字时改写。"""
    visible = _NON_WORD_RE.sub("", text)
    return bool(_PRONOUN_RE.search(text)) or len(visible) < 10


def expand_terms(
    text: str, expansions: Sequence[tuple[str, str]]
) -> tuple[str, ...]:
    """同义词/符号映射双向追加，返回要拼进查询的补充词。"""
    lowered = text.lower()
    found: list[str] = []
    for source, target in expansions:
        source, target = source.strip(), target.strip()
        if not source or not target:
            continue
        if source.lower() in lowered:
            found.append(target)
        elif target.lower() in lowered:
            found.append(source)
    return tuple(dict.fromkeys(found))


def is_broad_query(
    text: str,
    *,
    has_scope: bool,
    has_terms: bool,
) -> bool:
    """无条号、无标准限定、无术语命中且问法笼统时判为宽泛；数值条件不影响判定。"""
    if has_scope or has_terms:
        return False
    if _VAGUE_RE.search(text):
        return True
    return len(_NON_WORD_RE.sub("", text)) < 6


def _normalize_standard(raw: str | None) -> str | None:
    if raw is None:
        return None
    return re.sub(r"\s+", " ", raw).strip()


def _tidy(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text)
    cleaned = re.sub(r"\s+([，。；、,.!?；：])", r"\1", cleaned)
    cleaned = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", cleaned)
    return cleaned.strip()
