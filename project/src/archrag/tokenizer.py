"""bge-m3 tokenizer 懒加载：块长与上下文计量。

只加载 tokenizer（CPU、轻量），不加载模型；首次调用时初始化。
模型路径来自配置（本地目录或 HF 仓库 ID）。
"""

from __future__ import annotations

from typing import Any, Protocol


class TokenCounter(Protocol):
    """token 计数接口；切块与上下文组装按此注入。"""

    def count(self, text: str) -> int: ...


class BgeM3TokenCounter:
    """基于 bge-m3 tokenizer 的计数器，懒加载且不做导入期副作用。"""

    def __init__(self, model_path: str) -> None:
        self._model_path = model_path
        self._tokenizer: Any = None

    def count(self, text: str) -> int:
        return len(self._ensure().encode(text, add_special_tokens=False))

    def _ensure(self) -> Any:
        if self._tokenizer is None:
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(self._model_path, use_fast=True)
        return self._tokenizer
