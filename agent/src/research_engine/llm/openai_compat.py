from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI

from research_engine.types import ToolCall, TurnResult


class OpenAICompatLLM:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.model = model
        self._client = AsyncOpenAI(**kwargs)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        tool_choice: str = "auto",
        cancel: asyncio.Event | None = None,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> TurnResult:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        stream = await self._client.chat.completions.create(**kwargs)
        content_parts: list[str] = []
        tool_acc: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        saw_tools = False
        try:
            async for chunk in stream:
                if cancel is not None and cancel.is_set():
                    finish_reason = finish_reason or "cancelled"
                    break
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                reason = getattr(choice, "finish_reason", None)
                if reason:
                    finish_reason = reason
                delta = choice.delta
                tool_calls = getattr(delta, "tool_calls", None)
                if tool_calls:
                    saw_tools = True
                    for tc in tool_calls:
                        rec = tool_acc.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                        if tc.id:
                            rec["id"] = tc.id
                        fn = tc.function
                        if fn is None:
                            continue
                        if fn.name:
                            rec["name"] += fn.name
                        if fn.arguments:
                            rec["arguments"] += fn.arguments
                content = getattr(delta, "content", None)
                if content:
                    content_parts.append(content)
                    if on_delta and not saw_tools:
                        await on_delta(content)
        finally:
            aclose = getattr(stream, "aclose", None)
            if callable(aclose):
                await aclose()

        calls = [
            ToolCall(
                id=rec["id"] or f"call_{idx}",
                name=rec["name"],
                arguments=rec["arguments"] or "{}",
            )
            for idx, rec in sorted(tool_acc.items())
        ]
        return TurnResult(
            content="".join(content_parts),
            tool_calls=calls,
            finish_reason=finish_reason,
        )
