from __future__ import annotations

from types import SimpleNamespace

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


def _chunk(*, content: str | None = None, tool_calls: list | None = None):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=tool_calls))])


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
