"""DeepSeek 客户端参数与流式解析测试（不调用真实 API）。"""

from __future__ import annotations

from dataclasses import replace

from archrag.config import load_settings
from archrag.generation.client import DeepSeekClient


class _RecordedModel:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def stream(self, messages):
        return iter([])


def _client_with_settings(**overrides) -> DeepSeekClient:
    settings = replace(load_settings(), deepseek_api_key="sk-test", **overrides)
    return DeepSeekClient(settings)


def test_default_parameters_disable_thinking(monkeypatch) -> None:
    import langchain_deepseek

    monkeypatch.setattr(langchain_deepseek, "ChatDeepSeek", _RecordedModel)
    client = _client_with_settings()
    model = client._build(False)
    assert model.kwargs["temperature"] == 0.0
    assert model.kwargs["top_p"] == 0.95
    assert model.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert model.kwargs["timeout"] == 60
    assert model.kwargs["max_retries"] == 1


def test_thinking_parameters_have_no_temperature(monkeypatch) -> None:
    import langchain_deepseek

    monkeypatch.setattr(langchain_deepseek, "ChatDeepSeek", _RecordedModel)
    client = _client_with_settings()
    model = client._build(True)
    assert "temperature" not in model.kwargs
    assert model.kwargs["top_p"] == 1.0
    assert model.kwargs["reasoning_effort"] == "low"
    assert model.kwargs["extra_body"] == {"thinking": {"type": "enabled"}}


def test_stream_pieces_split_reasoning_and_content(monkeypatch) -> None:
    class Chunk:
        def __init__(self, content: str = "", reasoning: str = "") -> None:
            self.content = content
            self.additional_kwargs = {"reasoning_content": reasoning}

    class StreamingModel(_RecordedModel):
        def stream(self, messages):
            return iter([Chunk(reasoning="想"), Chunk(content="答"), Chunk(content="案")])

    import langchain_deepseek

    monkeypatch.setattr(langchain_deepseek, "ChatDeepSeek", StreamingModel)
    pieces = list(_client_with_settings().stream("系统", "问题", thinking=True))
    assert [(piece.kind, piece.text) for piece in pieces] == [
        ("reasoning", "想"),
        ("content", "答"),
        ("content", "案"),
    ]
