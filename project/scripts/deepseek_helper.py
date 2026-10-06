"""脚本共用的 DeepSeek 调用助手（批处理/评测用；运行时生成层见 M5）。"""

from __future__ import annotations

import json
import re

from archrag.config import load_settings


def chat(prompt: str, *, temperature: float = 0.3, max_tokens: int | None = None) -> str:
    """一次非流式调用，返回文本内容。"""
    settings = load_settings()
    api_key = settings.require_deepseek_api_key()
    from langchain_deepseek import ChatDeepSeek

    model = ChatDeepSeek(
        model=settings.model,
        api_key=api_key,
        base_url=settings.base_url,
        timeout=60,
        max_retries=1,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    response = model.invoke(prompt)
    content = getattr(response, "content", response)
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


def extract_json_array(text: str) -> list[dict]:
    """从模型输出中提取 JSON 数组（容忍 ```json 代码块）。"""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
    if fence is not None:
        cleaned = fence.group(1).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("模型输出中没有 JSON 数组")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, list):
        raise ValueError("模型输出不是 JSON 数组")
    return payload


def rewriter(
    prompt_template: str = (
        "把下面的问题改写为不依赖上下文的独立问题，只输出改写后的问题：\n{question}"
    ),
):
    """构造可注入检索链路的改写函数。"""

    def rewrite(question: str) -> str:
        return chat(
            prompt_template.format(question=question), temperature=0.0, max_tokens=64
        ).strip()

    return rewrite
