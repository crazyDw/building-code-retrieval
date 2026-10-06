"""健康检查：就绪、设备、Milvus 与降级原因码。"""

from __future__ import annotations

import torch
from fastapi import APIRouter

from archrag.api.deps import StateDep
from archrag.api.schemas import HealthResponse

router = APIRouter()
APP_VERSION = "0.1.0"


@router.get("/api/health", response_model=HealthResponse)
def health(state: StateDep) -> HealthResponse:
    gpu_available = torch.cuda.is_available()
    milvus_connected = False
    reason_code: str | None = None
    if not state.settings.dev_mode:
        try:
            milvus_connected = state.milvus.is_available()
        except Exception:
            milvus_connected = False
        if not milvus_connected:
            reason_code = "milvus_unavailable"
    ready = state.ready and (state.settings.dev_mode or milvus_connected)
    if not state.ready:
        reason_code = state.startup_error or "not_ready"
    if state.settings.dev_mode:
        device = "cpu"
    elif gpu_available and state.embedder.is_loaded:
        device = "cuda:0"
    else:
        device = state.settings.device
    return HealthResponse(
        ready=ready,
        warmup_done=state.warmup_done,
        device=device,
        gpu_available=gpu_available,
        rerank_enabled=state.settings.rerank_enabled,
        milvus_connected=milvus_connected,
        dev_mode=state.settings.dev_mode,
        version=APP_VERSION,
        status="ok" if ready else "unhealthy",
        reason_code=reason_code,
    )
