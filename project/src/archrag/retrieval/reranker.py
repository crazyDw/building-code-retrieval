"""bge-reranker-v2-m3：加载、设备校验与打分（256 token 截断）。"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from archrag.errors import ModelLoadError
from archrag.retrieval.device import find_module, memory_allocated, verify_module

_MODULE_PATHS = (("model",), ("model", "model"))
logger = logging.getLogger(__name__)


class BgeReranker:
    """懒加载重排模型；不提供 CPU 回退（铁律 16）。"""

    def __init__(
        self,
        model_path: str,
        *,
        devices: Sequence[str] = ("cuda:0",),
        use_fp16: bool = True,
        max_length: int = 256,
    ) -> None:
        self._model_path = model_path
        self._devices = tuple(devices)
        self._use_fp16 = use_fp16
        self._max_length = max_length
        self._model: Any = None
        self._memory_bytes = 0

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def memory_bytes(self) -> int:
        return self._memory_bytes

    def load(self) -> None:
        """加载并打分一次空样本，随后校验设备与精度。"""
        if self._model is not None:
            return
        from FlagEmbedding import FlagReranker

        self._model = FlagReranker(
            self._model_path,
            use_fp16=self._use_fp16,
            devices=list(self._devices),
        )
        self.warm_up()
        self._verify()
        self._memory_bytes = memory_allocated()
        logger.info(
            "reranker 加载完成：%s（设备 %s，fp16=%s，显存 %.1f MB）",
            self._model_path,
            self._devices[0],
            self._use_fp16,
            self._memory_bytes / 1024**2,
            extra={
                "event": "model_loaded",
                "model": self._model_path,
                "device": self._devices[0],
                "memory_allocated_mb": round(self._memory_bytes / 1024**2, 1),
            },
        )

    def warm_up(self) -> None:
        self.compute_score([("预热", "预热")], max_length=8)

    def compute_score(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        max_length: int | None = None,
    ) -> tuple[float, ...]:
        if self._model is None:
            raise ModelLoadError("reranker 尚未加载，请先调用 load()")
        if not pairs:
            return ()
        scores = self._model.compute_score(
            list(pairs),
            max_length=max_length or self._max_length,
        )
        if isinstance(scores, (int, float)):
            return (float(scores),)
        return tuple(float(score) for score in scores)

    def _verify(self) -> None:
        module = find_module(self._model, _MODULE_PATHS, "bge-reranker")
        expected_device = self._devices[0]
        expected_dtype = "torch.float16" if self._use_fp16 else None
        verify_module(
            module,
            device=expected_device,
            dtype=expected_dtype,
            label="bge-reranker",
        )
