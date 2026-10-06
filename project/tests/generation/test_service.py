"""生成编排测试：流式顺序、校验重生成、降级、条件与提示词（假客户端）。"""

from __future__ import annotations

import dataclasses
import hashlib
import sqlite3

import pytest

from archrag.config import load_settings
from archrag.corpus.chunker import build_chunks
from archrag.corpus.models import Standard
from archrag.corpus.parser import parse_text
from archrag.corpus.references import extract_references
from archrag.errors import GenerationError
from archrag.generation.client import DeepSeekClient, StreamPiece
from archrag.generation.prompts import DERIVATION_MARKER, ORIGINAL_MARKER
from archrag.generation.service import (
    ProjectCondition,
    extract_project_conditions,
    stream_answer,
)
from archrag.retrieval.context import ContextRequest, build_context
from archrag.retrieval.pipeline import ClauseHit, RetrievalResult
from archrag.retrieval.query import QueryPlan
from archrag.store.sqlite import SqliteStore

CLAUSE_ID = "GB 55031-2022_5.3.9"

VALID = (
    f"{DERIVATION_MARKER}\n"
    "按条文，楼梯踏步在离内侧扶手中心 0.25m 处宽度不应小于 0.22m。"
    f"[[clause:{CLAUSE_ID}]]\n"
    f"{ORIGINAL_MARKER}\n"
    "5.3.9 公共楼梯踏步的最小宽度和最大高度应符合表 5.3.9 的规定。"
    "螺旋楼梯和扇形踏步离内侧扶手中心 0.25m 处的踏步宽度不应小于 0.22m。"
    f"[[clause:{CLAUSE_ID}]]"
)

TAMPERED = (
    f"{DERIVATION_MARKER}\n"
    f"按条文取值。[[clause:{CLAUSE_ID}]]\n"
    f"{ORIGINAL_MARKER}\n"
    "螺旋楼梯和扇形踏步离内侧扶手中心 0.25m 处的踏步宽度不应小于 0.30m。"
    f"[[clause:{CLAUSE_ID}]]"
)


class FakeClient:
    """按脚本产出流式片段；记录每次调用的提示词与 thinking 开关。"""

    def __init__(self, answers, *, reasoning=(), error=None) -> None:
        self._answers = list(answers)
        self._reasoning = list(reasoning)
        self._error = error
        self.calls: list[dict] = []

    def stream(self, system: str, user: str, *, thinking: bool = False):
        self.calls.append({"system": system, "user": user, "thinking": thinking})
        if self._error is not None:
            raise self._error
        answer = self._answers.pop(0)
        for piece in self._reasoning:
            yield StreamPiece("reasoning", piece)
        for start in range(0, len(answer), 20):
            yield StreamPiece("content", answer[start : start + 20])


@pytest.fixture()
def store(tmp_path, parsed_corpus, chunks_by_standard, corpus_dir):
    sqlite = SqliteStore(tmp_path / "generation.sqlite")
    sqlite.initialize()
    name = "民用建筑通用规范.md"
    digest = hashlib.sha256((corpus_dir / name).read_bytes()).hexdigest()
    sqlite.replace_standard(
        parsed_corpus[name],
        chunks_by_standard[name],
        extract_references(parsed_corpus[name]),
        source_sha256=digest,
        version=digest[:12],
    )
    return sqlite


def _retrieval(
    store: SqliteStore,
    clause_ids=(CLAUSE_ID,),
    *,
    question="公共楼梯踏步宽度怎么定",
    numbers=(),
    broad=False,
    not_found=False,
) -> RetrievalResult:
    rows = {row["clause_id"]: row for row in store.clauses_by_ids(list(clause_ids))}
    hits = tuple(
        ClauseHit(
            clause_id=clause_id,
            clause_no=str(rows[clause_id]["clause_no"]),
            standard_id=str(rows[clause_id]["standard_id"]),
            score=1.0,
            rrf_score=1.0,
            rerank_score=1.0,
            matched_kuan=None,
            matched_chunk_type="body",
            matched_table_id=None,
            matched_row_no=None,
            is_reference=False,
        )
        for clause_id in clause_ids
    )
    context = build_context(
        store,
        [ContextRequest(clause_id=clause_id, score=1.0) for clause_id in clause_ids],
        count_tokens=lambda text: len(text) // 2,
        max_tokens=12000,
    )
    plan = QueryPlan(
        original=question,
        retrieval_text=question,
        clause_no=None,
        clause_standard_id=None,
        standard_scope=(),
        numbers=numbers,
        expanded_terms=(),
        rewrite_needed=False,
        rewrite_used=False,
        is_broad=broad,
    )
    return RetrievalResult(
        mode="search",
        plan=plan,
        hits=hits,
        context=context,
        not_found=not_found,
        degraded=False,
        degraded_reason=None,
        rerank_used=True,
        timings={},
        log_fields={},
    )


def _run(store, retrieval, client, **kwargs):
    return list(
        stream_answer(
            retrieval.plan.original,
            retrieval=retrieval,
            client=client,
            store=store,
            count_tokens=lambda text: len(text) // 2,
            **kwargs,
        )
    )


def _kinds(events) -> list[str]:
    return [event.kind for event in events]


def _done(events):
    return next(event.data for event in events if event.kind == "done")


def test_default_stream_order_and_validation(store) -> None:
    client = FakeClient([VALID])
    events = _run(store, _retrieval(store), client)
    kinds = _kinds(events)
    assert kinds[0] == "meta"
    assert kinds[-1] == "done"
    assert kinds.index("derivation") < kinds.index("original") < kinds.index("done")
    result = _done(events)
    assert result.fallback_flag is False
    assert result.text.startswith(DERIVATION_MARKER)
    assert ORIGINAL_MARKER in result.text
    assert result.citations == (CLAUSE_ID,)


def test_tampered_value_triggers_regeneration_without_leaking(store) -> None:
    client = FakeClient([TAMPERED, VALID])
    events = _run(store, _retrieval(store), client)
    assert "reset" in _kinds(events)
    emitted = "".join(
        event.data
        for event in events
        if event.kind in ("derivation", "original") and isinstance(event.data, str)
    )
    assert "0.30" not in emitted
    result = _done(events)
    assert result.attempts == 2
    assert result.fallback_flag is False
    assert "0.30" not in result.text


def test_regeneration_failure_falls_back_to_raw_clauses(store) -> None:
    client = FakeClient([TAMPERED, TAMPERED])
    events = _run(store, _retrieval(store), client)
    result = _done(events)
    assert result.fallback_flag is True
    assert "当前未提供归纳解读" in result.original
    assert "螺旋楼梯和扇形踏步" in result.original
    assert result.citations == (CLAUSE_ID,)


def test_api_error_falls_back(store) -> None:
    client = FakeClient([], error=GenerationError("boom"))
    events = _run(store, _retrieval(store), client)
    result = _done(events)
    assert result.fallback_flag is True
    assert "生成服务不可用" in result.original
    assert "5.3.9" in result.original


def test_missing_key_falls_back(store) -> None:
    settings = dataclasses.replace(load_settings(), deepseek_api_key="")
    events = _run(store, _retrieval(store), DeepSeekClient(settings))
    result = _done(events)
    assert result.fallback_flag is True
    assert "当前未提供归纳解读" in result.original


def test_deep_mode_streams_reasoning(store) -> None:
    client = FakeClient([VALID], reasoning=["先核对前提。", "再选择行次。"])
    events = _run(store, _retrieval(store), client, deep=True)
    assert _kinds(events).count("reasoning") == 2
    assert client.calls[0]["thinking"] is True
    assert _done(events).fallback_flag is False


def test_project_conditions_extraction_and_lock(store) -> None:
    question = "6层住宅，高度18m，二级耐火等级，设自动喷水灭火系统，踏步宽度怎么定？"
    keys = {condition.key for condition in extract_project_conditions(question)}
    assert {"使用性质", "层数", "建筑高度", "耐火等级", "自动灭火系统"} <= keys
    locked = ProjectCondition("层数", "层数", "7", "user", locked=True)
    client = FakeClient([VALID])
    events = _run(
        store, _retrieval(store, question=question), client, project_conditions=[locked]
    )
    meta = next(event.data for event in events if event.kind == "meta")
    conditions = {item["key"]: item for item in meta["project_conditions"]}
    assert conditions["层数"]["value"] == "7"
    assert conditions["层数"]["locked"] is True


def test_multi_question_asks_for_clarification(store) -> None:
    client = FakeClient(["您想先了解层高要求，还是防火分区划分？"])
    retrieval = _retrieval(store, question="层高有什么要求？防火分区怎么划分？")
    events = _run(store, retrieval, client)
    result = _done(events)
    assert result.fallback_flag is False
    assert "您想先了解" in result.derivation
    assert "先反问澄清" in client.calls[0]["system"]


def test_broad_question_prompt_and_flag(store) -> None:
    client = FakeClient([VALID])
    events = _run(store, _retrieval(store, question="有什么要求", broad=True), client)
    assert "不是完整清单" in client.calls[0]["user"]
    assert _done(events).broad is True


def test_forbidden_wording_is_aborted_before_leaking(store) -> None:
    bad = (
        f"{DERIVATION_MARKER}\n该做法满足规范要求。[[clause:{CLAUSE_ID}]]\n"
        f"{ORIGINAL_MARKER}\n5.3.9 公共楼梯踏步…[[clause:{CLAUSE_ID}]]"
    )
    client = FakeClient([bad, VALID])
    events = _run(store, _retrieval(store), client)
    emitted = "".join(
        event.data
        for event in events
        if event.kind in ("derivation", "original") and isinstance(event.data, str)
    )
    assert "满足规范" not in emitted
    result = _done(events)
    assert result.attempts == 2
    assert result.fallback_flag is False


def test_superseded_standard_notice(store) -> None:
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE standards SET superseded_by = 'GB 55031-2025' "
            "WHERE standard_id = 'GB 55031-2022'"
        )
    client = FakeClient([VALID])
    result = _done(_run(store, _retrieval(store), client))
    assert result.superseded_notice is not None
    assert "GB 55031-2025" in result.superseded_notice


def test_mandatory_standard_context_comes_first(tmp_path) -> None:
    sqlite = SqliteStore(tmp_path / "order.sqlite")
    sqlite.initialize()
    mandatory = parse_text(
        "# 1 总 则\n\n1.0.1 强制标准条文。\n",
        Standard("GB 10001-2025", "强制标准", "a.md", mandatory=True),
    )
    optional = parse_text(
        "# 1 总 则\n\n1.0.1 推荐标准条文。\n",
        Standard("GB 10002-2025", "推荐标准", "b.md", mandatory=False),
    )
    def counter(text: str) -> int:
        return len(text) // 2

    for index, parsed in enumerate((mandatory, optional)):
        chunks = build_chunks(parsed, version="v1", count_tokens=counter)
        sqlite.replace_standard(
            parsed, chunks, (), source_sha256=str(index) * 64, version="v1"
        )
    retrieval = _retrieval(
        sqlite,
        clause_ids=("GB 10002-2025_1.0.1", "GB 10001-2025_1.0.1"),
        question="要求",
    )
    client = FakeClient(
        [
            f"{DERIVATION_MARKER}\n按条文。[[clause:GB 10001-2025_1.0.1]]\n"
            f"{ORIGINAL_MARKER}\n1.0.1 强制标准条文。[[clause:GB 10001-2025_1.0.1]]"
        ]
    )
    _run(sqlite, retrieval, client)
    assert retrieval.context.text.index("强制标准") < retrieval.context.text.index("推荐标准")
