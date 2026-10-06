"""DeepSeek 流式客户端：默认/深度参数分离，60 s 超时、重试 1 次。

实测（2026-10-05）：langchain-deepseek 通过 `extra_body={"thinking": {...}}`
控制思考开关；`deepseek-flash` 默认会输出 reasoning_content，默认路径必须显式 disabled。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from archrag.config import Settings
from archrag.errors import GenerationError

logger = logging.getLogger(__name__)
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 1


@dataclass(frozen=True, slots=True)
class StreamPiece:
    """流式片段：reasoning（思考）或 content（正文）。"""

    kind: str
    text: str


class DeepSeekClient:
    """按调用模式构造 ChatDeepSeek；不做导入期副作用。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def stream(
        self,
        system: str,
        user: str,
        *,
        thinking: bool = False,
    ) -> Iterator[StreamPiece]:
        """流式调用；失败抛 GenerationError（由上层降级）。"""
        try:
            model = self._build(thinking)
            for chunk in model.stream([("system", system), ("human", user)]):
                reasoning = str(chunk.additional_kwargs.get("reasoning_content") or "")
                if reasoning:
                    yield StreamPiece("reasoning", reasoning)
                content = chunk.content
                if isinstance(content, str) and content:
                    yield StreamPiece("content", content)
                elif content:
                    yield StreamPiece("content", str(content))
        except GenerationError:
            raise
        except Exception as exc:  # 网络/超时/鉴权等统一转成 GenerationError
            raise GenerationError(f"生成 API 调用失败：{type(exc).__name__}") from exc

    def _build(self, thinking: bool) -> Any:
        api_key = self._settings.require_deepseek_api_key()
        from langchain_deepseek import ChatDeepSeek

        kwargs: dict[str, Any] = {
            "model": self._settings.model,
            "api_key": api_key,
            "base_url": self._settings.base_url,
            "timeout": REQUEST_TIMEOUT_SECONDS,
            "max_retries": MAX_RETRIES,
        }
        if thinking:
            kwargs["reasoning_effort"] = self._settings.reasoning_effort or "low"
            kwargs["top_p"] = 1.0
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        else:
            kwargs["temperature"] = 0.0
            kwargs["top_p"] = 0.95
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        return ChatDeepSeek(**kwargs)
