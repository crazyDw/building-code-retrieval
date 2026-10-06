"""入库接口契约测试（含 DEV_MODE 隔离；文件名避免与 M2 的 test_ingest.py 重名）。"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

from fastapi.testclient import TestClient
from support import build_app, build_settings

from archrag.store.sqlite import SqliteStore


def _prepare_corpus(tmp_path: Path, corpus_dir: Path, names) -> Path:
    corpus = tmp_path / "corpus"
    corpus.mkdir(exist_ok=True)
    for name in names:
        shutil.copy(corpus_dir / name, corpus / name)
    source_map = (corpus_dir / "规范标准号映射表.md").read_text(encoding="utf-8")
    lines = [
        line
        for line in source_map.splitlines()
        if line.startswith("|")
        and (
            line.startswith("| 文件名")
            or line.startswith("|---")
            or any(name in line for name in names)
        )
    ]
    (corpus / "map.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return corpus


def _settings_for(tmp_path: Path, corpus: Path, *, dev_mode: bool):
    settings = build_settings(tmp_path, dev_mode=dev_mode)
    return dataclasses.replace(settings, standard_map_path=corpus / "map.md")


def test_ingest_is_idempotent_and_rejects_new_version(tmp_path, corpus_dir) -> None:
    corpus = _prepare_corpus(tmp_path, corpus_dir, ["民用建筑通用规范.md"])
    settings = _settings_for(tmp_path, corpus, dev_mode=False)
    store = SqliteStore(settings.sqlite_path)
    store.initialize()
    app, state = build_app(settings, store, warmup=False)
    state.ready = True
    with TestClient(app) as client:
        first = client.post("/api/ingest", json={"file_name": "民用建筑通用规范.md"})
        assert first.status_code == 200
        body = first.json()
        assert body["created"] is True
        assert body["clauses"] == 142
        assert body["chunks"] == 147
        assert body["reindexed"] == {"GB 55031-2022": 147}
        before = store.counts()
        second = client.post("/api/ingest", json={"file_name": "民用建筑通用规范.md"})
        assert second.status_code == 200
        assert second.json()["created"] is False
        assert store.counts()["clauses"] == before["clauses"]
        with (corpus / "民用建筑通用规范.md").open("a", encoding="utf-8") as handle:
            handle.write("\n")
        conflict = client.post("/api/ingest", json={"file_name": "民用建筑通用规范.md"})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "version_conflict"


def test_ingest_dev_mode_stays_in_dev_database(tmp_path, corpus_dir) -> None:
    corpus = _prepare_corpus(
        tmp_path, corpus_dir, ["民用建筑通用规范.md", "住宅项目规范.md"]
    )
    settings = _settings_for(tmp_path, corpus, dev_mode=True)
    store = SqliteStore(settings.sqlite_path)
    store.initialize()
    app, state = build_app(settings, store, warmup=True)
    with TestClient(app) as client:
        response = client.post("/api/ingest", json={"file_name": "民用建筑通用规范.md"})
        limited = client.post("/api/ingest", json={"file_name": "住宅项目规范.md"})
    assert response.status_code == 200
    body = response.json()
    assert body["dev_mode"] is True
    assert body["reindexed"] is None
    assert store.counts()["clauses"] == 142
    assert state.milvus.calls == []
    assert "_dev" in settings.sqlite_path.name
    assert limited.status_code == 400
    assert limited.json()["detail"]["code"] == "dev_mode_limited"
