"""FastAPI 应用工厂：lifespan 预热、就绪门与静态挂载；强制单 worker 由启动命令保证。"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from archrag.api import catalog, chat, health, ingest
from archrag.api.deps import AppState
from archrag.config import Settings, load_settings
from archrag.errors import StoreError
from archrag.generation.client import DeepSeekClient
from archrag.logging_setup import setup_logging
from archrag.retrieval.embedder import BgeM3Embedder
from archrag.retrieval.reranker import BgeReranker
from archrag.store.milvus import MilvusStore
from archrag.store.sqlite import SqliteStore
from archrag.tokenizer import BgeM3TokenCounter

logger = logging.getLogger(__name__)


def build_state(settings: Settings) -> AppState:
    return AppState(
        settings=settings,
        store=SqliteStore(settings.sqlite_path),
        milvus=MilvusStore(settings.milvus_uri, settings.milvus_collection),
        embedder=BgeM3Embedder(settings.embed_model),
        reranker=BgeReranker(settings.rerank_model),
        client=DeepSeekClient(settings),
        token_counter=BgeM3TokenCounter(settings.embed_model),
    )


def create_app(
    settings: Settings | None = None,
    *,
    services: AppState | None = None,
    warmup: bool = True,
) -> FastAPI:
    """应用工厂；测试可注入 services 并关闭预热。"""
    settings = settings or (services.settings if services else load_settings())
    state = services or build_state(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not settings.dev_mode:
            _assert_single_worker()
        setup_logging(settings.repo_root / "logs", console=False)
        if warmup:
            if settings.dev_mode:
                state.warmup_done = True
                state.ready = True
            else:
                try:
                    await anyio.to_thread.run_sync(_warm_up, state)
                except Exception as exc:
                    state.startup_error = type(exc).__name__
                    state.ready = False
                    logger.error("预热失败：%s", type(exc).__name__)
                    raise
                state.warmup_done = True
                state.milvus_connected = True
                state.ready = True
        yield

    app = FastAPI(title="建筑规范 RAG 智能检索助手", version=health.APP_VERSION, lifespan=lifespan)
    app.state.services = state
    app.include_router(health.router)
    app.include_router(catalog.router)
    app.include_router(chat.router)
    app.include_router(ingest.router)
    frontend_dist = settings.repo_root / "project" / "frontend" / "dist"
    if frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    return app


def _warm_up(state: AppState) -> None:
    """预热：Milvus 可达 + embedder 空推理 + reranker 打分各一次（D3/D10）。"""
    if not state.milvus.is_available():
        raise StoreError("Milvus 不可达，启动失败（fail fast）")
    state.embedder.load()
    state.reranker.load()


def _assert_single_worker() -> None:
    """模型常驻进程强制单 worker（D3）：多 worker 会让显存与模型数翻倍。"""
    for index, item in enumerate(sys.argv):
        if item == "--workers" and index + 1 < len(sys.argv) and sys.argv[index + 1] != "1":
            raise RuntimeError("模型常驻进程必须 workers=1")
        if item.startswith("--workers=") and item.split("=", 1)[1] != "1":
            raise RuntimeError("模型常驻进程必须 workers=1")
    concurrency = os.environ.get("WEB_CONCURRENCY")
    if concurrency and concurrency != "1":
        raise RuntimeError("模型常驻进程必须 WEB_CONCURRENCY=1")


app = create_app()
