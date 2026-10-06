"""生成结果校验：分隔标记、引用、原文数值、推导输入值、禁止措辞与 scope/注误用。"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from archrag.generation import prompts

_CITATION_RE = re.compile(r"\[\[clause:([^\]]+)\]\]")
_CLAUSE_MENTION_RE = re.compile(r"\d+\.\d+\.\d+")
_STANDARD_RE = re.compile(r"GB\s*\d{5}(?:-\d{4})?")
_TABLE_REF_RE = re.compile(r"表\s*\d+(?:\.\d+){2}(?:-\d+)?")
_NUMBER_RE = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])\s*"
    r"(mm|cm|m2|㎡|m|%|度|℃|年|层|米|h|dB|lx|MPa|kN|N|个|人)?"
)
_FORBIDDEN_RE = re.compile(r"(满足规范|合规|合格)")
_NOTE_BASIS_RE = re.compile(r"(根据|依据|按照)[^。；\n]{0,14}(注\s*[:：]|表中注|备注)")
_SCOPE_BASIS_RE = re.compile(r"(根据|依据|按照)[^。；\n]{0,14}适用范围")


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """拆分后的两块文本、引用与违规项。"""

    derivation: str
    original: str
    citations: tuple[str, ...]
    violations: tuple[str, ...]


def split_sections(text: str) -> tuple[str, str]:
    """按 <!--原文--> 拆分；没有标记时整段视为推导。"""
    match = prompts.find_original_marker(text)
    if match is None:
        return prompts.strip_derivation_marker(text).strip(), ""
    derivation = prompts.strip_derivation_marker(text[: match.start()]).strip()
    original = text[match.end() :].strip()
    return derivation, original


def extract_citations(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_CITATION_RE.findall(text)))


def extract_values(text: str) -> tuple[str, ...]:
    """抽取数值（含单位），并剔除引用标记、条号、表号与标准号。"""
    cleaned = _CITATION_RE.sub(" ", text)
    cleaned = _STANDARD_RE.sub(" ", cleaned)
    cleaned = _TABLE_REF_RE.sub(" ", cleaned)
    cleaned = _CLAUSE_MENTION_RE.sub(" ", cleaned)
    values: list[str] = []
    for match in _NUMBER_RE.finditer(cleaned):
        token = (match.group(1) + (match.group(2) or "")).replace(" ", "")
        values.append(token)
    return tuple(values)


def numeric_core(value: str) -> str:
    match = re.match(r"\d+(?:\.\d+)?", value)
    return match.group(0) if match else value


def normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def stream_violations(text: str) -> tuple[str, ...]:
    """流式增量可即时发现的违规（禁止措辞、scope/注作依据）。"""
    violations: list[str] = []
    if _FORBIDDEN_RE.search(text):
        violations.append("forbidden_wording")
    if _NOTE_BASIS_RE.search(text):
        violations.append("note_as_basis")
    if _SCOPE_BASIS_RE.search(text):
        violations.append("scope_as_basis")
    return tuple(violations)


def validate_answer(
    text: str,
    *,
    allowed_clause_ids: Sequence[str],
    source_texts: Sequence[str],
    input_values: Sequence[str] = (),
    clarification: bool = False,
) -> ValidationResult:
    """完整校验；返回违规清单（空 = 通过）。"""
    derivation, original = split_sections(text)
    citations = extract_citations(text)
    violations: list[str] = []
    if clarification and prompts.find_original_marker(text) is None and not citations:
        return ValidationResult(
            derivation=text.strip(),
            original="",
            citations=(),
            violations=(),
        )
    if prompts.find_original_marker(text) is None:
        violations.append("missing_original_marker")
    if not original:
        violations.append("empty_original_block")
    allowed = set(allowed_clause_ids)
    unknown = sorted({item for item in citations if item not in allowed})
    if unknown:
        violations.append("unknown_citation:" + ",".join(unknown[:3]))
    if not citations:
        violations.append("missing_citations")

    source_normalized = normalize_for_match("".join(source_texts))
    source_numbers = set(re.findall(r"\d+(?:\.\d+)?", source_normalized))
    mismatched = [
        value
        for value in extract_values(original)
        if numeric_core(value) not in source_numbers
    ]
    if mismatched:
        violations.append("original_value_mismatch:" + ",".join(mismatched[:3]))

    violations.extend(stream_violations(derivation))
    values = extract_values(derivation)
    inputs = [value for value in input_values if value]
    input_cores = {numeric_core(value) for value in inputs}
    if values and inputs:
        derived = [
            value
            for value in values
            if numeric_core(value) not in source_numbers
            and numeric_core(value) not in input_cores
        ]
        derivation_normalized = normalize_for_match(derivation)
        mentioned = any(
            normalize_for_match(value) in derivation_normalized for value in inputs
        )
        if derived and not mentioned:
            violations.append("missing_inputs")
    elif values and any(numeric_core(value) not in source_numbers for value in values):
        violations.append("missing_inputs")
    return ValidationResult(
        derivation=derivation,
        original=original,
        citations=citations,
        violations=tuple(dict.fromkeys(violations)),
    )
