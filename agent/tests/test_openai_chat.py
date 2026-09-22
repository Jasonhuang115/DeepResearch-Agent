from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_service.llm.openai_chat import OpenAILLM


class _Stream:
    def __init__(self, chunks: list) -> None:
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)

    async def aclose(self) -> None:
        return None


def _chunk(*, content: str | None = None, tool_calls: list | None = None, reasoning_content: str | None = None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=tool_calls, reasoning_content=reasoning_content),
                finish_reason=None,
            )
        ]
    )


def _tool_delta(*, index: int, id: str | None = None, name: str | None = None, arguments: str | None = None):
    return SimpleNamespace(
        index=index,
        id=id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


@pytest.mark.asyncio
async def test_openai_buffers_streamed_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [
        _chunk(content="Looking up "),
        _chunk(content="sources."),
        _chunk(tool_calls=[_tool_delta(index=0, id="call_1", name="web_", arguments="")]),
        _chunk(tool_calls=[_tool_delta(index=0, name="search", arguments='{"query":')]),
        _chunk(tool_calls=[_tool_delta(index=0, arguments='"solid state"}')]),
    ]
    llm = OpenAILLM(api_key="sk-test", model="gpt-4.1-mini")

    async def fake_create(**_kwargs):
        return _Stream(chunks)

    monkeypatch.setattr(llm._client.chat.completions, "create", fake_create)
    result = await llm.complete(
        [{"role": "user", "content": "q"}],
        [{"type": "function", "function": {"name": "web_search"}}],
    )
    assert result.content == "Looking up sources."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call_1"
    assert result.tool_calls[0].name == "web_search"
    assert result.tool_calls[0].arguments == '{"query":"solid state"}'


@pytest.mark.asyncio
async def test_openai_forwards_reasoning_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [
        _chunk(reasoning_content="Check the "),
        _chunk(reasoning_content="timeline."),
        _chunk(content="CATL is still in trial production."),
    ]
    llm = OpenAILLM(api_key="sk-test", model="gpt-4.1-mini")

    async def fake_create(**_kwargs):
        return _Stream(chunks)

    monkeypatch.setattr(llm._client.chat.completions, "create", fake_create)
    reasoning: list[str] = []
    text: list[str] = []
    result = await llm.complete(
        [{"role": "user", "content": "q"}],
        [],
        on_delta=async_append(text),
        on_reasoning=async_append(reasoning),
    )
    assert result.content == "CATL is still in trial production."
    assert "".join(reasoning) == "Check the timeline."
    assert "".join(text) == "CATL is still in trial production."


@pytest.mark.asyncio
async def test_openai_sends_thinking_extra_body(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    llm = OpenAILLM(
        api_key="sk-test",
        model="deepseek-flash",
        extra_body={"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
    )

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return _Stream([_chunk(content="ok")])

    monkeypatch.setattr(llm._client.chat.completions, "create", fake_create)
    await llm.complete([{"role": "user", "content": "q"}], [])
    assert captured["model"] == "deepseek-flash"
    assert captured["extra_body"] == {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}
    assert captured["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_openai_reads_usage_from_chunk_without_choices(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    chunks = [
        _chunk(content="hi"),
        SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7)),
    ]
    llm = OpenAILLM(api_key="sk-test", model="gpt-4.1-mini")

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return _Stream(chunks)

    monkeypatch.setattr(llm._client.chat.completions, "create", fake_create)
    result = await llm.complete([{"role": "user", "content": "q"}], [])
    assert result.content == "hi"
    assert result.usage is not None
    assert result.usage.prompt_tokens == 11
    assert result.usage.completion_tokens == 7
    assert captured["stream_options"] == {"include_usage": True}


def async_append(parts: list[str]):
    async def _on(piece: str) -> None:
        parts.append(piece)

    return _on
