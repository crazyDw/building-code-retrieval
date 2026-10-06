"""API 测试的公共夹具。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from support import build_app, build_settings, build_store


@pytest.fixture()
def api_env(tmp_path, parsed_corpus, chunks_by_standard, corpus_dir):
    settings = build_settings(tmp_path)
    store = build_store(tmp_path, parsed_corpus, chunks_by_standard, corpus_dir)
    app, state = build_app(settings, store)
    state.ready = True
    state.warmup_done = True
    with TestClient(app) as client:
        yield client, state


@pytest.fixture()
def api_client(api_env):
    client, state = api_env
    return client
