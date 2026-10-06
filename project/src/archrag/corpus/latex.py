"""LaTeX 片段处理：符号还原为可读文本，并产出「符号 → 中文术语」候选。

本批语料里的 LaTeX 基本都是单位与符号；真正的数学公式保留原文，
不参与还原，也不进符号候选（数值校验另在生成层做）。
"""

from __future__ import annotations

import re

from archrag.corpus.models import LatexOccurrence, SymbolCandidate

_DISPLAY_RE = re.compile(r"\$\$(?P<body>.+?)\$\$", re.S)
_MATH_RE = re.compile(r"(?<!\$)\$(?!\$)(?P<body>.+?)(?<!\$)\$(?!\$)", re.S)
_FORMULA_RE = re.compile(
    r"\\(?:frac|dfrac|tfrac|sqrt|sum|prod|int|iint|oint|lim|begin|overline|underline|widehat)\b"
)
_SCRIPT_RE = re.compile(r"[_^]\{([^{}]*)\}")
_SINGLE_SCRIPT_RE = re.compile(r"[_^]([A-Za-z0-9])")
_TEXT_COMMAND_RE = re.compile(r"\\(?:text|mathrm|operatorname|mathit|mathbf)\s*\{([^{}]*)\}")
_SPACING_COMMAND_RE = re.compile(r"\\(?:,|;|:|!|\s)")

_GREEK = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "kappa": "κ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "phi": "φ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
    "Delta": "Δ",
    "Sigma": "Σ",
    "Phi": "Φ",
    "Omega": "Ω",
}

_SYMBOLS = {
    "\\geqslant": "≥",
    "\\geq": "≥",
    "\\leqslant": "≤",
    "\\leq": "≤",
    "\\times": "×",
    "\\cdot": "·",
    "\\circ": "°",
    "\\sim": "~",
    "\\%": "%",
}

_COMPACT_AFTER_RE = re.compile(r"([≥≤×·~])\s*")
_CJK_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]{2,}")
_TRAILING_STOP_WORDS = (
    "不应小于",
    "不应大于",
    "不应低于",
    "不应高于",
    "不宜小于",
    "不小于",
    "不大于",
    "不低于",
    "不高于",
    "小于",
    "大于",
    "应为",
)


def restore(text: str) -> str:
    """把行内 LaTeX 符号还原为可读文本；真公式原样保留。"""

    def _replace(match: re.Match[str]) -> str:
        restored = _restore_body(match.group("body"))
        return match.group(0) if restored is None else restored

    return _MATH_RE.sub(_replace, text)


def extract(text: str) -> tuple[LatexOccurrence, ...]:
    """提取全部行内 LaTeX 片段及其还原结果。"""
    occurrences: list[LatexOccurrence] = []
    display_ranges: list[tuple[int, int]] = []
    for match in _DISPLAY_RE.finditer(text):
        display_ranges.append((match.start(), match.end()))
        occurrences.append(
            LatexOccurrence(
                raw=match.group(0),
                restored=match.group(0),
                start=match.start(),
                end=match.end(),
                is_formula=True,
            )
        )
    for match in _MATH_RE.finditer(text):
        if any(start <= match.start() < end for start, end in display_ranges):
            continue
        restored = _restore_body(match.group("body"))
        occurrences.append(
            LatexOccurrence(
                raw=match.group(0),
                restored=match.group(0) if restored is None else restored,
                start=match.start(),
                end=match.end(),
                is_formula=restored is None,
            )
        )
    occurrences.sort(key=lambda item: item.start)
    return tuple(occurrences)


def candidates(text: str) -> tuple[SymbolCandidate, ...]:
    """从出现位置附近的中文短语产出符号候选，供人工审核。"""
    result: list[SymbolCandidate] = []
    for occurrence in extract(text):
        if occurrence.is_formula:
            continue
        result.append(
            SymbolCandidate(
                symbol=occurrence.restored,
                term=_term_before(text, occurrence.start),
                context=_context(text, occurrence.start, occurrence.end),
            )
        )
    return tuple(result)


def _restore_body(body: str) -> str | None:
    """还原单个片段；判定为真公式时返回 None。"""
    if _FORMULA_RE.search(body):
        return None
    text = body
    for _ in range(len(_GREEK) + 1):
        updated = _TEXT_COMMAND_RE.sub(r"\1", text)
        updated = _SPACING_COMMAND_RE.sub(" ", updated)
        updated = updated.replace("~", " ")
        for name, symbol in _GREEK.items():
            updated = re.sub(rf"\\{name}(?![A-Za-z])", symbol, updated)
        for command, symbol in _SYMBOLS.items():
            updated = updated.replace(command, symbol)
        updated = re.sub(r"\\(?:left|right)\b", "", updated)
        updated = _SCRIPT_RE.sub(r"\1", updated)
        updated = _SINGLE_SCRIPT_RE.sub(r"\1", updated)
        updated = updated.replace("{", "").replace("}", "")
        if updated == text:
            break
        text = updated
    text = re.sub(r"(?<=[α-ωΑ-Ω])\s+(?=[A-Za-z])", "", text)
    text = _COMPACT_AFTER_RE.sub(r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _term_before(text: str, position: int) -> str | None:
    prefix = text[:position]
    matches = list(_CJK_RUN_RE.finditer(prefix))
    last_match = matches[-1] if matches else None
    if last_match is None:
        return None
    gap = prefix[last_match.end() :]
    if len(gap) > 6:
        return None
    term = last_match.group(0)[-18:]
    for stop_word in _TRAILING_STOP_WORDS:
        if term.endswith(stop_word):
            term = term[: -len(stop_word)]
            break
    return term or None


def _context(text: str, start: int, end: int, window: int = 40) -> str:
    snippet = text[max(0, start - window) : end + window]
    return re.sub(r"\s+", " ", snippet).strip()
