from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FinishKind(StrEnum):
    COMPLETED = "completed"
    TOOL_CALLS = "tool_calls"
    OUTPUT_LIMIT = "output_limit"
    FILTERED = "filtered"
    ERROR = "error"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FinishInfo:
    kind: FinishKind
    provider_reason: str | None = None


_COMPLETED = {"stop", "end_turn", "stop_sequence", "completed"}
_TOOL_CALLS = {"tool_calls", "tool_use", "function_call", "function_calls"}
_OUTPUT_LIMIT = {
    "length",
    "max_tokens",
    "max_output_tokens",
    "max_completion_tokens",
    "incomplete",
}
_FILTERED = {"content_filter", "refusal", "safety", "filtered"}
_CANCELLED = {"aborted", "cancelled", "canceled"}


def normalize_finish(
    provider_reason: str | None,
    *,
    has_tool_calls: bool,
    cancelled: bool,
) -> FinishInfo:
    if cancelled:
        return FinishInfo(FinishKind.CANCELLED, provider_reason)
    raw = provider_reason.strip().lower() if isinstance(provider_reason, str) and provider_reason.strip() else None
    if raw in _CANCELLED:
        return FinishInfo(FinishKind.CANCELLED, provider_reason)
    if raw in _OUTPUT_LIMIT:
        return FinishInfo(FinishKind.OUTPUT_LIMIT, provider_reason)
    if raw in _FILTERED:
        return FinishInfo(FinishKind.FILTERED, provider_reason)
    if raw in _TOOL_CALLS or has_tool_calls:
        return FinishInfo(FinishKind.TOOL_CALLS, provider_reason)
    if raw in _COMPLETED or raw is None:
        return FinishInfo(FinishKind.COMPLETED, provider_reason)
    return FinishInfo(FinishKind.UNKNOWN, provider_reason)
