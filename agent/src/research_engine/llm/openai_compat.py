from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI

from research_engine.types import TokenUsage, ToolCall, TurnResult


def _delta_reasoning(delta: Any) -> str:
    for key in ("reasoning_content", "reasoning"):
        val = getattr(delta, key, None)
        if isinstance(val, str) and val:
            return val
    extra = getattr(delta, "model_extra", None) or {}
    if isinstance(extra, dict):
        for key in ("reasoning_content", "reasoning"):
            val = extra.get(key)
            if isinstance(val, str) and val:
                return val
    return ""


class OpenAICompatLLM:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.model = model
        self._extra_body = extra_body
        self._client = AsyncOpenAI(**kwargs)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        tool_choice: str = "auto",
        cancel: asyncio.Event | None = None,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning: Callable[[str], Awaitable[None]] | None = None,
    ) -> TurnResult:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body
        kwargs["stream_options"] = {"include_usage": True}

        stream = await self._client.chat.completions.create(**kwargs)
        content_parts: list[str] = []
        tool_acc: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        saw_tools = False
        usage: TokenUsage | None = None
        try:
            async for chunk in stream:
                if cancel is not None and cancel.is_set():
                    finish_reason = finish_reason or "cancelled"
                    break
                parsed = _usage_from(chunk)
                if parsed is not None:
                    usage = parsed
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
                reasoning = _delta_reasoning(delta)
                if reasoning and on_reasoning:
                    await on_reasoning(reasoning)
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
            usage=usage,
        )


def _usage_from(chunk: Any) -> TokenUsage | None:
    raw = getattr(chunk, "usage", None)
    if raw is None and isinstance(chunk, dict):
        raw = chunk.get("usage")
    if raw is None:
        return None
    if isinstance(raw, dict):
        prompt = raw.get("prompt_tokens")
        completion = raw.get("completion_tokens")
    else:
        prompt = getattr(raw, "prompt_tokens", None)
        completion = getattr(raw, "completion_tokens", None)
    if prompt is None and completion is None:
        return None
    return TokenUsage(prompt_tokens=int(prompt or 0), completion_tokens=int(completion or 0))
