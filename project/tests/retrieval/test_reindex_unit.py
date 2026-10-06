"""DEV_MODE 下不连接 Milvus、不加载模型。"""

from __future__ import annotations

from archrag.retrieval.embedder import BgeM3Embedder
from archrag.retrieval.reindex import reindex
from archrag.store.milvus import MilvusStore
from archrag.store.sqlite import SqliteStore


def test_dev_mode_skips_milvus_and_models(tmp_path) -> None:
    sqlite_store = SqliteStore(tmp_path / "empty.sqlite")
    sqlite_store.initialize()
    milvus = MilvusStore("http://127.0.0.1:1", "unused")
    embedder = BgeM3Embedder("missing-model")
    report = reindex(sqlite_store, milvus, embedder, dev_mode=True)
    assert report.counts == {}
    assert report.embedded == 0
    assert embedder.is_loaded is False
