"""应用状态与依赖注入。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from archrag.config import Settings
from archrag.generation.client import DeepSeekClient
from archrag.retrieval.embedder import BgeM3Embedder
from archrag.retrieval.reranker import BgeReranker
from archrag.store.milvus import MilvusStore
from archrag.store.sqlite import SqliteStore
from archrag.tokenizer import BgeM3TokenCounter


@dataclass
class AppState:
    """一次应用进程的共享服务句柄与就绪状态。"""

    settings: Settings
    store: SqliteStore
    milvus: MilvusStore
    embedder: BgeM3Embedder
    reranker: BgeReranker
    client: DeepSeekClient
    token_counter: BgeM3TokenCounter
    ready: bool = False
    warmup_done: bool = False
    milvus_connected: bool = False
    startup_error: str | None = None


def get_state(request: Request) -> AppState:
    return request.app.state.services


def require_ready(state: Annotated[AppState, Depends(get_state)]) -> AppState:
    if not state.ready:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_ready", "message": "服务尚未预热完成"},
        )
    return state


StateDep = Annotated[AppState, Depends(get_state)]
ReadyDep = Annotated[AppState, Depends(require_ready)]
