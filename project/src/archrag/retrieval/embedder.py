"""bge-m3 嵌入：一次前向产出 dense（1024 维）+ sparse。"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from archrag.errors import ModelLoadError
from archrag.retrieval.device import find_module, memory_allocated, verify_module

_MODULE_PATHS = (("model", "model"), ("model",))
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    """一批文本的向量：dense 定长、sparse 为 token_id→权重。"""

    dense: tuple[tuple[float, ...], ...]
    sparse: tuple[dict[int, float], ...]


class BgeM3Embedder:
    """懒加载、显式预热与校验；不做导入期副作用。"""

    def __init__(
        self,
        model_path: str,
        *,
        devices: Sequence[str] = ("cuda:0",),
        use_fp16: bool = True,
        batch_size: int = 16,
        max_length: int = 512,
    ) -> None:
        self._model_path = model_path
        self._devices = tuple(devices)
        self._use_fp16 = use_fp16
        self._batch_size = batch_size
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
        """加载并预热一次，随后校验设备与精度。"""
        if self._model is not None:
            return
        from FlagEmbedding import BGEM3FlagModel

        self._model = BGEM3FlagModel(
            self._model_path,
            use_fp16=self._use_fp16,
            devices=list(self._devices),
        )
        self.warm_up()
        self._verify()
        self._memory_bytes = memory_allocated()
        logger.info(
            "embedder 加载完成：%s（设备 %s，fp16=%s，显存 %.1f MB）",
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
        """空推理一次，触发 FlagEmbedding 把权重搬到目标设备。"""
        self.encode(["预热"], batch_size=1, max_length=8)

    def encode(
        self,
        texts: Sequence[str],
        *,
        batch_size: int | None = None,
        max_length: int | None = None,
    ) -> EmbeddingBatch:
        if self._model is None:
            raise ModelLoadError("embedder 尚未加载，请先调用 load()")
        if not texts:
            return EmbeddingBatch(dense=(), sparse=())
        output = self._model.encode(
            list(texts),
            batch_size=batch_size or self._batch_size,
            max_length=max_length or self._max_length,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense = tuple(tuple(float(value) for value in row) for row in output["dense_vecs"])
        sparse = tuple(
            {int(token): float(weight) for token, weight in weights.items()}
            for weights in output["lexical_weights"]
        )
        return EmbeddingBatch(dense=dense, sparse=sparse)

    def _verify(self) -> None:
        module = find_module(self._model, _MODULE_PATHS, "bge-m3 embedder")
        expected_device = self._devices[0]
        expected_dtype = "torch.float16" if self._use_fp16 else None
        verify_module(
            module,
            device=expected_device,
            dtype=expected_dtype,
            label="bge-m3 embedder",
        )
