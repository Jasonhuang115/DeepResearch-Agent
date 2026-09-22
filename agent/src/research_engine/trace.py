from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from research_engine.types import TokenUsage, TurnResult

_CLIP = 200
_OVERFLOW_MARKERS = ("chars omitted", "truncated; full result was not saved")


class Span(Protocol):
    def annotate(self, **fields: Any) -> None: ...


class Tracer(Protocol):
    def span(self, name: str, **fields: Any) -> Iterator[Span]: ...

    def add_usage(self, prompt_tokens: int, completion_tokens: int) -> None: ...

    def add_search(self) -> None: ...

    def add_turn(self) -> None: ...


class NullSpan:
    def annotate(self, **fields: Any) -> None:
        return None


class NullTracer:
    def trace(self, name: str, **fields: Any) -> Iterator[Span]:
        return self.span(name)

    @contextmanager
    def span(self, name: str, **fields: Any) -> Iterator[Span]:
        _ = (name, fields)
        yield NullSpan()

    def add_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        return None

    def add_search(self) -> None:
        return None

    def add_turn(self) -> None:
        return None

    def current_turns(self) -> int:
        return 0

    def detach_inherited(self) -> None:
        return None

    def flush(self) -> None:
        return None


def clip(value: str, limit: int = _CLIP) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def tool_input(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Fields safe to send to a trace. Never file bodies or fetched text."""
    if name == "web_search":
        return {"query": clip(str(args.get("query") or ""))}
    if name == "web_fetch":
        return {"url": clip(str(args.get("url") or ""))}
    if name == "Bash":
        return {"command": clip(str(args.get("command") or ""))}
    if name == "spawn_subagent":
        return {"id": clip(str(args.get("id") or ""))}
    if name in {"Write", "Edit"}:
        return {"path": clip(str(args.get("path") or ""))}
    out: dict[str, Any] = {}
    if args.get("path"):
        out["path"] = clip(str(args.get("path") or ""))
    if args.get("pattern"):
        out["pattern"] = clip(str(args.get("pattern") or ""))
    if args.get("glob"):
        out["glob"] = clip(str(args.get("glob") or ""))
    if not out:
        out["keys"] = sorted(str(key) for key in args)
    return out


def result_overflowed(text: str) -> bool:
    return any(marker in text for marker in _OVERFLOW_MARKERS)


def usage_dict(result: TurnResult) -> dict[str, int] | None:
    usage: TokenUsage | None = result.usage
    if usage is None:
        return None
    prompt = int(usage.prompt_tokens or 0)
    completion = int(usage.completion_tokens or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }
