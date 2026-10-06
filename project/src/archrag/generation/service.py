"""生成编排：默认/深度两条路径、流式校验顺序、重生成与纯检索降级。"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from archrag.errors import GenerationError
from archrag.generation import prompts, validate
from archrag.generation.client import DeepSeekClient
from archrag.retrieval.context import ContextRequest, ContextResult, build_context
from archrag.retrieval.pipeline import RetrievalResult
from archrag.store.sqlite import SqliteStore

_USE_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "使用性质",
        r"(住宅|办公建筑|办公楼|商业建筑|商场|旅馆|学校|医院|幼儿园|老年人|"
        r"公共建筑|工业建筑|车库)",
    ),
    ("层数", r"(\d+)\s*层"),
    ("建筑高度", r"(?<!层)(?:高度|高)\s*(\d+(?:\.\d+)?)\s*(?:m|米)"),
    ("耐火等级", r"([一二三四甲乙])\s*级?\s*耐火等级|耐火等级\s*([一二三四甲乙])\s*级?"),
    ("自动灭火系统", r"(自动喷水灭火系统|自动灭火系统|喷淋|自动喷淋)"),
)


@dataclass(frozen=True, slots=True)
class ProjectCondition:
    """项目条件：自动抽取或用户手改；locked 项后续轮次优先。"""

    key: str
    label: str
    value: str
    source: str
    locked: bool = False


@dataclass(frozen=True, slots=True)
class GenerationEvent:
    """流式事件：meta / reasoning / derivation / reset / original / done。"""

    kind: str
    data: Any


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """一轮生成的完整结果。"""

    text: str
    derivation: str
    original: str
    citations: tuple[str, ...]
    fallback_flag: bool
    degraded_flag: bool
    degraded_reason: str | None
    rerank_used: bool
    project_conditions: tuple[ProjectCondition, ...]
    superseded_notice: str | None
    broad: bool
    not_found: bool
    numbers: tuple[str, ...]
    attempts: int
    timings: dict[str, float] = field(default_factory=dict)


def extract_project_conditions(question: str) -> tuple[ProjectCondition, ...]:
    """规则抽取项目条件（使用性质/层数/高度/耐火等级/自动灭火系统）。"""
    conditions: list[ProjectCondition] = []
    for label, pattern in _USE_PATTERNS:
        match = re.search(pattern, question)
        if match is None:
            continue
        value = next((group for group in match.groups() if group), match.group(0))
        conditions.append(
            ProjectCondition(
                key=label,
                label=label,
                value=str(value).strip(),
                source="auto",
            )
        )
    return tuple(conditions)


def merge_project_conditions(
    auto: Sequence[ProjectCondition],
    provided: Sequence[ProjectCondition],
) -> tuple[ProjectCondition, ...]:
    """合并：已提供（含用户锁定）的键覆盖自动抽取结果。"""
    merged: dict[str, ProjectCondition] = {item.key: item for item in auto}
    for item in provided:
        merged[item.key] = item
    return tuple(merged.values())


def is_multi_question(question: str) -> bool:
    return question.count("？") + question.count("?") >= 2


def stream_answer(
    question: str,
    *,
    retrieval: RetrievalResult,
    client: DeepSeekClient,
    store: SqliteStore,
    count_tokens: Callable[[str], int],
    project_conditions: Sequence[ProjectCondition] = (),
    referenced_clause_ids: Sequence[str] = (),
    deep: bool = False,
    max_attempts: int = 2,
    context_max_tokens: int = 12000,
) -> Iterator[GenerationEvent]:
    """流式生成：推导增量下发，原文块校验通过后才发；失败退纯检索。"""
    started = time.monotonic()
    conditions = merge_project_conditions(
        extract_project_conditions(question), project_conditions
    )
    context = _build_context(
        retrieval,
        store,
        referenced_clause_ids,
        count_tokens=count_tokens,
        max_tokens=context_max_tokens,
    )
    allowed_ids = tuple(clause.clause_id for clause in context.clauses)
    source_texts = [
        clause.text + "\n" + "\n".join(clause.tables) for clause in context.clauses
    ] + list(context.scope_qualifiers)
    input_values = tuple(number.raw for number in retrieval.plan.numbers) + tuple(
        condition.value for condition in conditions
    )
    superseded = _superseded_notice(store, allowed_ids)
    clarification = is_multi_question(question)
    meta = {
        "fallback_flag": False,
        "degraded_flag": retrieval.degraded,
        "degraded_reason": retrieval.degraded_reason,
        "rerank_used": retrieval.rerank_used,
        "not_found": retrieval.not_found,
        "broad": retrieval.plan.is_broad,
        "superseded_notice": superseded,
        "project_conditions": [_asdict(condition) for condition in conditions],
        "numbers": [number.raw for number in retrieval.plan.numbers],
    }
    yield GenerationEvent("meta", meta)

    system = prompts.build_system_prompt(store.approved_terms(50), deep=deep)
    base_user = prompts.build_user_prompt(
        question=question,
        context_text=context.text,
        numbers=retrieval.plan.numbers,
        conditions=[(item.label, item.value, item.locked) for item in conditions],
        referenced_clause_ids=referenced_clause_ids,
        broad=retrieval.plan.is_broad,
        not_found=retrieval.not_found,
        deep=deep,
    )
    last_violations: tuple[str, ...] = ()
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            yield GenerationEvent("reset", {"reason": last_violations})
        user = base_user + (
            prompts.build_repair_instruction(last_violations) if last_violations else ""
        )
        parser = _StreamParser()
        aborted: tuple[str, ...] | None = None
        try:
            for piece in client.stream(system, user, thinking=deep):
                if piece.kind == "reasoning":
                    yield GenerationEvent("reasoning", piece.text)
                    continue
                delta = parser.feed(piece.text)
                if delta:
                    violations = validate.stream_violations(parser.derivation_text())
                    if violations:
                        aborted = violations
                        break
                    yield GenerationEvent("derivation", delta)
        except GenerationError:
            yield from _emit_fallback(
                retrieval,
                context,
                conditions,
                superseded,
                reason="api_error",
                attempts=attempt,
                started=started,
            )
            return

        full_text = parser.full
        result = validate.validate_answer(
            full_text,
            allowed_clause_ids=allowed_ids,
            source_texts=source_texts,
            input_values=input_values,
            clarification=clarification,
        )
        violations = tuple(dict.fromkeys((*result.violations, *(aborted or ()))))
        if not violations:
            final_text = _assemble(result.derivation, result.original)
            timings = {"total_ms": _ms(started)}
            yield GenerationEvent("original", result.original)
            done = GenerationResult(
                text=final_text,
                derivation=result.derivation,
                original=result.original,
                citations=result.citations,
                fallback_flag=False,
                degraded_flag=retrieval.degraded,
                degraded_reason=retrieval.degraded_reason,
                rerank_used=retrieval.rerank_used,
                project_conditions=conditions,
                superseded_notice=superseded,
                broad=retrieval.plan.is_broad,
                not_found=retrieval.not_found,
                numbers=tuple(number.raw for number in retrieval.plan.numbers),
                attempts=attempt,
                timings=timings,
            )
            yield GenerationEvent("done", done)
            return
        last_violations = violations

    yield from _emit_fallback(
        retrieval,
        context,
        conditions,
        superseded,
        reason="validation_failed",
        attempts=max_attempts,
        started=started,
    )


def generate_answer(
    question: str,
    *,
    retrieval: RetrievalResult,
    client: DeepSeekClient,
    store: SqliteStore,
    count_tokens: Callable[[str], int],
    project_conditions: Sequence[ProjectCondition] = (),
    referenced_clause_ids: Sequence[str] = (),
    deep: bool = False,
) -> GenerationResult:
    """消费流式事件并返回 done 结果（非流式调用方使用）。"""
    result: GenerationResult | None = None
    for event in stream_answer(
        question,
        retrieval=retrieval,
        client=client,
        store=store,
        count_tokens=count_tokens,
        project_conditions=project_conditions,
        referenced_clause_ids=referenced_clause_ids,
        deep=deep,
    ):
        if event.kind == "done":
            result = event.data
    if result is None:
        raise GenerationError("生成流程未产出结果")
    return result


class _StreamParser:
    """把模型流拆成推导增量与原文缓冲；标记可能被拆包，先压住再判。"""

    def __init__(self) -> None:
        self.full = ""
        self._emitted = 0
        self._in_original = False
        self._original_start: int | None = None

    def feed(self, text: str) -> str | None:
        self.full += text
        if self._in_original:
            return None
        match = prompts.find_original_marker(self.full)
        if match is not None:
            derivation = prompts.strip_derivation_marker(
                self.full[: match.start()]
            ).strip()
            delta = derivation[self._emitted :]
            self._emitted = len(derivation)
            self._in_original = True
            self._original_start = match.end()
            return delta or None
        visible = prompts.strip_derivation_marker(self.full).lstrip()
        cut = _marker_safe_cut(visible)
        delta = visible[self._emitted : cut]
        self._emitted = cut
        return delta or None

    def derivation_text(self) -> str:
        match = prompts.find_original_marker(self.full)
        if match is None:
            return prompts.strip_derivation_marker(self.full).strip()
        return prompts.strip_derivation_marker(self.full[: match.start()]).strip()

    @property
    def original(self) -> str:
        if self._original_start is None:
            return ""
        return self.full[self._original_start :]


def _marker_safe_cut(text: str) -> int:
    markers = (prompts.DERIVATION_MARKER, prompts.ORIGINAL_MARKER)
    cut = len(text)
    for candidate in range(len(text), max(len(text) - 12, -1), -1):
        tail = text[candidate:]
        if any(marker.startswith(tail) for marker in markers):
            cut = candidate
    while cut > 0 and text[cut - 1] in " \t\r\n" and len(text) - cut < 16:
        cut -= 1
    return cut


def _build_context(
    retrieval: RetrievalResult,
    store: SqliteStore,
    referenced_clause_ids: Sequence[str],
    *,
    count_tokens: Callable[[str], int],
    max_tokens: int,
) -> ContextResult:
    requests = [
        ContextRequest(
            clause_id=hit.clause_id,
            score=hit.rerank_score if hit.rerank_score is not None else hit.score,
            matched_kuan=hit.matched_kuan,
            is_reference=hit.is_reference,
        )
        for hit in retrieval.hits
    ]
    known = {request.clause_id for request in requests}
    for clause_id in referenced_clause_ids:
        if clause_id not in known:
            requests.append(
                ContextRequest(clause_id=clause_id, score=0.0, is_reference=True)
            )
            known.add(clause_id)
    return build_context(store, requests, count_tokens=count_tokens, max_tokens=max_tokens)


def _superseded_notice(store: SqliteStore, clause_ids: Sequence[str]) -> str | None:
    standard_ids = sorted({clause_id.rsplit("_", 1)[0] for clause_id in clause_ids})
    superseded = store.superseded_by_map(standard_ids)
    if not superseded:
        return None
    pairs = "；".join(f"{old} 已被 {new} 替代" for old, new in sorted(superseded.items()))
    return f"{pairs}，请核对适用性。"


def _emit_fallback(
    retrieval: RetrievalResult,
    context: ContextResult,
    conditions: Sequence[ProjectCondition],
    superseded: str | None,
    *,
    reason: str,
    attempts: int,
    started: float,
) -> Iterator[GenerationEvent]:
    message = (
        "当前未提供归纳解读：生成服务不可用，以下为检索到的条文原文与适用范围。"
        if reason == "api_error"
        else "当前未提供归纳解读：生成结果未通过校验，以下为检索到的条文原文与适用范围。"
    )
    original = f"{context.text}\n\n（{message}）"
    text = f"{prompts.ORIGINAL_MARKER}\n{original}"
    yield GenerationEvent("original", original)
    yield GenerationEvent(
        "done",
        GenerationResult(
            text=text,
            derivation="",
            original=original,
            citations=tuple(clause.clause_id for clause in context.clauses),
            fallback_flag=True,
            degraded_flag=retrieval.degraded,
            degraded_reason=retrieval.degraded_reason,
            rerank_used=retrieval.rerank_used,
            project_conditions=tuple(conditions),
            superseded_notice=superseded,
            broad=retrieval.plan.is_broad,
            not_found=retrieval.not_found,
            numbers=tuple(number.raw for number in retrieval.plan.numbers),
            attempts=attempts,
            timings={"total_ms": _ms(started)},
        ),
    )


def _assemble(derivation: str, original: str) -> str:
    if derivation:
        if not original:
            return f"{prompts.DERIVATION_MARKER}\n{derivation}"
        return f"{prompts.DERIVATION_MARKER}\n{derivation}\n\n{prompts.ORIGINAL_MARKER}\n{original}"
    return f"{prompts.ORIGINAL_MARKER}\n{original}"


def _asdict(item: Any) -> dict[str, Any]:
    return {name: getattr(item, name) for name in item.__slots__}


def _ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 2)
