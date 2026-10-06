"""健康检查契约测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient
from support import build_app, build_settings, build_store


def test_health_before_warmup_reports_not_ready(
    tmp_path, parsed_corpus, chunks_by_standard, corpus_dir
):
    store = build_store(tmp_path, parsed_corpus, chunks_by_standard, corpus_dir)
    app, state = build_app(build_settings(tmp_path), store, warmup=False)
    with TestClient(app) as client:
        response = client.get("/api/health")
    body = response.json()
    assert response.status_code == 200
    assert body["ready"] is False
    assert body["warmup_done"] is False
    assert body["status"] == "unhealthy"
    assert body["reason_code"] == "not_ready"
    assert set(body) >= {
        "ready",
        "warmup_done",
        "device",
        "gpu_available",
        "rerank_enabled",
        "milvus_connected",
        "dev_mode",
        "version",
    }


def test_health_ready_fields(api_client) -> None:
    body = api_client.get("/api/health").json()
    assert body["ready"] is True
    assert body["warmup_done"] is True
    assert body["status"] == "ok"
    assert body["reason_code"] is None
    assert body["milvus_connected"] is True
    assert body["dev_mode"] is False
    assert body["rerank_enabled"] is True
    assert body["version"]


def test_health_turns_unhealthy_when_milvus_drops(api_env) -> None:
    client, state = api_env
    state.milvus.is_available = lambda: False
    body = client.get("/api/health").json()
    assert body["ready"] is False
    assert body["status"] == "unhealthy"
    assert body["reason_code"] == "milvus_unavailable"


def test_health_dev_mode_ready_without_gpu(
    tmp_path, parsed_corpus, chunks_by_standard, corpus_dir
) -> None:
    store = build_store(tmp_path, parsed_corpus, chunks_by_standard, corpus_dir)
    app, _ = build_app(build_settings(tmp_path, dev_mode=True), store, warmup=True)
    with TestClient(app) as client:
        body = client.get("/api/health").json()
    assert body["ready"] is True
    assert body["dev_mode"] is True
    assert body["device"] == "cpu"
    assert body["milvus_connected"] is False


def test_multiple_workers_are_rejected(
    tmp_path, parsed_corpus, chunks_by_standard, corpus_dir, monkeypatch
) -> None:
    import pytest

    store = build_store(tmp_path, parsed_corpus, chunks_by_standard, corpus_dir)
    app, _ = build_app(build_settings(tmp_path), store, warmup=False)
    monkeypatch.setattr("sys.argv", ["uvicorn", "--workers", "2"])
    with pytest.raises(RuntimeError), TestClient(app):
        pass
