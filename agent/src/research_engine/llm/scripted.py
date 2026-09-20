from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from research_engine.types import TurnResult


class ScriptedLLM:
    """Test double: returns queued TurnResults and records complete() calls."""

    model = "scripted"

    def __init__(self, turns: list[TurnResult] | None = None) -> None:
        self._turns = list(turns or [])
        self.calls: list[dict[str, Any]] = []

    def push(self, result: TurnResult) -> None:
        self._turns.append(result)

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
        self.calls.append(
            {
                "messages": [dict(m) for m in messages],
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        if cancel is not None and cancel.is_set():
            return TurnResult(finish_reason="cancelled")
        _ = on_reasoning
        if not self._turns:
            return TurnResult(finish_reason="stop")
        turn = self._turns.pop(0)
        if on_delta and turn.content and not turn.tool_calls:
            await on_delta(turn.content)
        reason = turn.finish_reason or ("tool_calls" if turn.tool_calls else "stop")
        return TurnResult(content=turn.content, tool_calls=turn.tool_calls, finish_reason=reason)
