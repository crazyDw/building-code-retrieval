#!/usr/bin/env python3
"""DeepSeek API 冒烟：验证 key 可用并记录 API 侧首 token 延迟基线。

用法（仓库根执行，先在 .env 填好 DEEPSEEK_API_KEY）:
    & "D:\\Ai software\\anaconda3\\envs\\archrag\\python.exe" project\\scripts\\smoke_deepseek.py

退出码：0 成功 / 1 请求失败 / 2 未配置 key。输出不包含密钥。
"""

from __future__ import annotations

import sys
import time

from archrag.config import load_settings
from archrag.errors import ConfigError

PROMPT = "只回复两个字：收到"


def main() -> int:
    settings = load_settings()
    try:
        api_key = settings.require_deepseek_api_key()
    except ConfigError as exc:
        print(f"跳过：{exc}")
        return 2

    from langchain_deepseek import ChatDeepSeek

    model = ChatDeepSeek(
        model=settings.model,
        api_key=api_key,
        base_url=settings.base_url,
        timeout=60,
        max_retries=1,
        temperature=0,
    )
    started = time.monotonic()
    first_chunk_at: float | None = None
    chunks = 0
    try:
        for _ in model.stream(PROMPT):
            chunks += 1
            if first_chunk_at is None:
                first_chunk_at = time.monotonic()
    except Exception as exc:  # 冒烟脚本：失败信息用于报告，重新抛出不提供更多信息
        print(f"失败：{type(exc).__name__}: {str(exc)[:300]}")
        return 1

    if first_chunk_at is None:
        print("失败：未收到任何增量")
        return 1
    print(f"key: 可用 | model: {settings.model} | base_url: {settings.base_url}")
    print(f"first_token_ms: {round((first_chunk_at - started) * 1000)}")
    print(f"chunks: {chunks}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
