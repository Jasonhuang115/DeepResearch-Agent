from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class TurnResult:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: TokenUsage | None = None


class LLMClient(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        tool_choice: str = "auto",
        cancel: asyncio.Event | None = None,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning: Callable[[str], Awaitable[None]] | None = None,
    ) -> TurnResult: ...


class EventEmitter(Protocol):
    async def emit(self, typ: str, payload: dict | None = None) -> None: ...


class ToolBox(Protocol):
    def get(self, name: str) -> Callable[[dict[str, Any]], Awaitable[str]] | None: ...

    def openai_tools(self) -> list[dict[str, Any]]: ...
