"""问答 SSE 契约测试。"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from support import (
    CLAUSE_ID,
    TAMPERED,
    VALID,
    FakeClient,
    body_chunk_id,
    build_app,
    build_settings,
    build_store,
    parse_sse,
    table_chunk_id,
)

from archrag.errors import GenerationError
from archrag.generation.client import StreamPiece
from archrag.generation.service import generate_answer
from archrag.retrieval.pipeline import PipelineConfig, retrieve


def _chat(client, payload) -> list[tuple[str, dict]]:
    with client.stream("POST", "/api/chat", json=payload) as response:
        assert response.status_code == 200
        return parse_sse(response.iter_lines())


def _configure_milvus(state, chunk_ids) -> None:
    state.milvus.dense_ids = list(chunk_ids)
    state.milvus.sparse_ids = list(chunk_ids)


def test_chat_events_and_done_payload(api_env, chunks_by_standard) -> None:
    client, state = api_env
    _configure_milvus(state, [body_chunk_id(chunks_by_standard, "民用建筑通用规范.md", "5.3.9")])
    state.client = FakeClient([VALID])
    events = _chat(client, {"message": "公共楼梯踏步宽度怎么定"})
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "meta"
    assert kinds[-1] == "done"
    blocks = [(data["block"], data["delta"]) for kind, data in events if kind == "answer"]
    assert blocks[0][0] == "derivation"
    assert any(block == "original" for block, _ in blocks)
    done = events[-1][1]
    for key in (
        "citations",
        "tables",
        "section_hint",
        "fallback_flag",
        "degraded_flag",
        "rerank_used",
        "superseded_notice",
        "project_conditions",
        "numbers",
        "mode",
        "dev_mode",
        "attempts",
        "timings",
    ):
        assert key in done, key
    assert done["citations"][0]["clause_id"] == CLAUSE_ID
    assert done["citations"][0]["path"]
    assert done["section_hint"]["section_clause_count"] >= 1
    assert done["fallback_flag"] is False

    streamed = "".join(delta for _, delta in blocks)
    retrieval = retrieve(
        "公共楼梯踏步宽度怎么定",
        store=state.store,
        milvus=state.milvus,
        embedder=state.embedder,
        reranker=state.reranker,
        config=PipelineConfig.from_settings(state.settings),
        count_tokens=state.token_counter.count,
    )
    expected = generate_answer(
        "公共楼梯踏步宽度怎么定",
        retrieval=retrieval,
        client=FakeClient([VALID]),
        store=state.store,
        count_tokens=state.token_counter.count,
    )
    assert streamed == expected.derivation + expected.original


def test_chat_table_payload_highlights_matched_row(api_env, chunks_by_standard) -> None:
    client, state = api_env
    table_chunk = table_chunk_id(chunks_by_standard, "住宅项目规范.md", "3.1.1")
    _configure_milvus(state, [table_chunk])
    state.client = FakeClient([], error=GenerationError("boom"))
    events = _chat(client, {"message": "空间环境控制指标"})
    done = events[-1][1]
    target = next(table for table in done["tables"] if table["table_id"] == "表 3.1.1-1")
    assert target["clause_id"] == "GB 55038-2025_3.1.1"
    assert target["highlight_rows"]
    assert target["rows"]
    assert done["fallback_flag"] is True


def test_chat_clause_shortcut_skips_generation(api_env) -> None:
    client, state = api_env
    state.client = FakeClient([])
    events = _chat(client, {"message": "5.3.9"})
    assert state.client.calls == []
    done = events[-1][1]
    assert done["mode"] == "clause_shortcut"
    assert any(
        data["block"] == "original" and "踏步" in data["delta"]
        for kind, data in events
        if kind == "answer"
    )
    assert done["fallback_flag"] is False


def test_chat_not_ready_returns_503(
    tmp_path, parsed_corpus, chunks_by_standard, corpus_dir
) -> None:
    store = build_store(tmp_path, parsed_corpus, chunks_by_standard, corpus_dir)
    app, _ = build_app(build_settings(tmp_path), store, warmup=False)
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"message": "楼梯要求"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "not_ready"


def test_chat_unexpected_error_emits_error_then_done(api_env, chunks_by_standard) -> None:
    client, state = api_env
    _configure_milvus(state, [body_chunk_id(chunks_by_standard, "民用建筑通用规范.md", "5.3.9")])
    state.client = FakeClient([], error=RuntimeError("boom"))
    events = _chat(client, {"message": "公共楼梯踏步宽度怎么定"})
    error = next(data for kind, data in events if kind == "error")
    assert error["code"] == "generation_failed"
    done = events[-1][1]
    assert events[-1][0] == "done"
    assert done["fallback_flag"] is True


def test_chat_reset_event_on_regeneration(api_env, chunks_by_standard) -> None:
    client, state = api_env
    _configure_milvus(state, [body_chunk_id(chunks_by_standard, "民用建筑通用规范.md", "5.3.9")])
    state.client = FakeClient([TAMPERED, VALID])
    events = _chat(client, {"message": "公共楼梯踏步宽度怎么定"})
    assert "reset" in [kind for kind, _ in events]
    assert events[-1][1]["fallback_flag"] is False


def test_chat_locked_conditions_passthrough(api_env, chunks_by_standard) -> None:
    client, state = api_env
    _configure_milvus(state, [body_chunk_id(chunks_by_standard, "民用建筑通用规范.md", "5.3.9")])
    state.client = FakeClient([VALID])
    events = _chat(
        client,
        {
            "message": "楼梯踏步宽度怎么定",
            "project_conditions": [
                {"key": "层数", "label": "层数", "value": "7", "locked": True}
            ],
        },
    )
    conditions = {item["key"]: item for item in events[-1][1]["project_conditions"]}
    assert conditions["层数"]["value"] == "7"
    assert conditions["层数"]["locked"] is True


def test_chat_superseded_notice_passthrough(api_env, chunks_by_standard) -> None:
    import sqlite3

    client, state = api_env
    _configure_milvus(state, [body_chunk_id(chunks_by_standard, "民用建筑通用规范.md", "5.3.9")])
    state.client = FakeClient([VALID])
    with sqlite3.connect(state.store.path) as connection:
        connection.execute(
            "UPDATE standards SET superseded_by = 'GB 55031-2025' "
            "WHERE standard_id = 'GB 55031-2022'"
        )
    events = _chat(client, {"message": "公共楼梯踏步宽度怎么定"})
    done = events[-1][1]
    assert done["superseded_notice"] and "GB 55031-2025" in done["superseded_notice"]


def test_chat_dev_mode_uses_like_search(
    tmp_path, parsed_corpus, chunks_by_standard, corpus_dir
) -> None:
    store = build_store(
        tmp_path, parsed_corpus, chunks_by_standard, corpus_dir, names=("民用建筑通用规范.md",)
    )
    settings = build_settings(tmp_path, dev_mode=True)
    app, state = build_app(settings, store, client=FakeClient([VALID]), warmup=True)
    with TestClient(app) as client:
        events = _chat(client, {"message": "楼梯踏步宽度"})
    assert events[0][1]["dev_mode"] is True
    done = events[-1][1]
    assert done["citations"]
    assert done["dev_mode"] is True
    assert "search_dense" not in state.milvus.calls


def test_closing_stream_stops_generation(api_env, chunks_by_standard) -> None:
    from archrag.generation.service import stream_answer

    _, state = api_env
    _configure_milvus(state, [body_chunk_id(chunks_by_standard, "民用建筑通用规范.md", "5.3.9")])
    retrieval = retrieve(
        "公共楼梯踏步宽度怎么定",
        store=state.store,
        milvus=state.milvus,
        embedder=state.embedder,
        reranker=state.reranker,
        config=PipelineConfig.from_settings(state.settings),
        count_tokens=state.token_counter.count,
    )

    class CountingClient:
        def __init__(self) -> None:
            self.produced = 0

        def stream(
            self, system: str, user: str, *, thinking: bool = False
        ) -> Iterator[StreamPiece]:
            for index in range(200):
                self.produced += 1
                yield StreamPiece("content", f"内容{index}")

    counting = CountingClient()
    generator = stream_answer(
        "公共楼梯踏步宽度怎么定",
        retrieval=retrieval,
        client=counting,
        store=state.store,
        count_tokens=state.token_counter.count,
    )
    next(generator)
    next(generator)
    generator.close()
    assert 0 < counting.produced < 200
