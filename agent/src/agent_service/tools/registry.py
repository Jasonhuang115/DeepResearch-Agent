from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

ToolFn = Callable[[dict[str, Any]], Awaitable[str]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolFn] = {}

    def register(self, name: str, fn: ToolFn) -> None:
        self._tools[name] = fn

    def get(self, name: str) -> ToolFn | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)
