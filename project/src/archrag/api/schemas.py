"""请求/响应模型（与 docs/api 对齐）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectConditionIn(BaseModel):
    key: str
    label: str | None = None
    value: str
    locked: bool = False


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    deep_analysis: bool = False
    project_conditions: list[ProjectConditionIn] = Field(default_factory=list)
    referenced_clause_ids: list[str] = Field(default_factory=list)


class IngestRequest(BaseModel):
    file_name: str | None = None
    standard_id: str | None = None


class HealthResponse(BaseModel):
    ready: bool
    warmup_done: bool
    device: str
    gpu_available: bool
    rerank_enabled: bool
    milvus_connected: bool
    dev_mode: bool
    version: str
    status: str
    reason_code: str | None = None
