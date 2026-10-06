"""术语候选：统计共现 + 表格条件词 + LaTeX 符号映射；别名以映射表为种子。

产物是候选，不是正式词典；人工审核（M4）后才进检索用表。
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from archrag.corpus.models import Alias, Expansion, LexiconTerm, ParsedStandard

_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_STOP_CHARS = frozenset("的了和与及或等可须应不应为其有无在上下内外时后前中非各本规范条")
_NAME_SUFFIXES = ("通用规范", "项目规范")


@dataclass(frozen=True, slots=True)
class LexiconCandidates:
    """三类候选的集合。"""

    terms: tuple[LexiconTerm, ...]
    aliases: tuple[Alias, ...]
    expansions: tuple[Expansion, ...]


def build_candidates(
    parsed_list: Sequence[ParsedStandard],
    *,
    top_n: int = 500,
    min_freq: int = 5,
    table_min_freq: int = 2,
) -> LexiconCandidates:
    """从全量解析结果生成候选词典、别名与查询扩展。"""
    clause_texts = [clause.text for parsed in parsed_list for clause in parsed.clauses]
    table_texts = [
        cell
        for parsed in parsed_list
        for table in parsed.tables
        for row in table.rows
        for cell in row
    ]
    table_texts.extend(table.caption for parsed in parsed_list for table in parsed.tables)

    merged: dict[str, LexiconTerm] = {}
    for term in _ngram_terms(clause_texts, source="stats", min_freq=min_freq, top_n=top_n):
        merged[term.term] = term
    for term in _ngram_terms(
        table_texts, source="table", min_freq=table_min_freq, top_n=top_n
    ):
        existing = merged.get(term.term)
        if existing is None:
            merged[term.term] = term
        else:
            merged[term.term] = LexiconTerm(
                term=term.term,
                freq=existing.freq + term.freq,
                score=max(existing.score, term.score),
                source="stats+table",
            )
    terms = tuple(
        sorted(merged.values(), key=lambda item: (-item.score, -item.freq, item.term))[:top_n]
    )

    aliases: list[Alias] = []
    expansions: list[Expansion] = []
    seen_aliases: set[tuple[str, str]] = set()
    seen_expansions: set[tuple[str, str]] = set()
    for parsed in parsed_list:
        standard = parsed.standard
        names = [standard.standard_id, standard.name]
        for suffix in _NAME_SUFFIXES:
            if standard.name.endswith(suffix):
                short = standard.name[: -len(suffix)].strip()
                if short:
                    names.append(short)
        for index, name in enumerate(names):
            key = (standard.standard_id, name)
            if not name or key in seen_aliases:
                continue
            seen_aliases.add(key)
            alias_type = (
                "standard_id" if index == 0 else ("full_name" if index == 1 else "short_name")
            )
            aliases.append(
                Alias(standard_id=standard.standard_id, alias=name, alias_type=alias_type)
            )
        for candidate in parsed.symbol_candidates:
            if not candidate.term or candidate.term == candidate.symbol:
                continue
            key = (candidate.symbol, candidate.term)
            if key in seen_expansions:
                continue
            seen_expansions.add(key)
            expansions.append(
                Expansion(
                    from_text=candidate.symbol,
                    to_text=candidate.term,
                    kind="latex_symbol",
                )
            )
    return LexiconCandidates(
        terms=terms,
        aliases=tuple(aliases),
        expansions=tuple(expansions),
    )


def write_candidates(candidates: LexiconCandidates, path: Path) -> Path:
    """写出候选 JSON（data/lexicon/，不入库）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "terms": [_asdict(item) for item in candidates.terms],
        "aliases": [_asdict(item) for item in candidates.aliases],
        "expansions": [_asdict(item) for item in candidates.expansions],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _asdict(item: Any) -> dict[str, object]:
    return {field: getattr(item, field) for field in item.__slots__}


def _ngram_terms(
    texts: Sequence[str],
    *,
    source: str,
    min_freq: int,
    top_n: int,
) -> tuple[LexiconTerm, ...]:
    counts: Counter[str] = Counter()
    left: defaultdict[str, Counter[str]] = defaultdict(Counter)
    right: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for text in texts:
        for run in _CJK_RUN_RE.findall(text):
            for size in (2, 3, 4):
                for start in range(len(run) - size + 1):
                    gram = run[start : start + size]
                    if any(char in _STOP_CHARS for char in gram):
                        continue
                    counts[gram] += 1
                    if start > 0:
                        left[gram][run[start - 1]] += 1
                    if start + size < len(run):
                        right[gram][run[start + size]] += 1
    scored = [
        LexiconTerm(
            term=gram,
            freq=freq,
            score=round(math.log2(freq) + min(_entropy(left[gram]), _entropy(right[gram])), 4),
            source=source,
        )
        for gram, freq in counts.items()
        if freq >= min_freq
    ]
    scored.sort(key=lambda item: (-item.score, -item.freq, item.term))
    return tuple(scored[:top_n])


def _entropy(counter: Counter[str]) -> float:
    total = sum(counter.values())
    if total <= 1:
        return 0.0
    return -sum(
        (count / total) * math.log2(count / total) for count in counter.values() if count
    )
