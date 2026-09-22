"""Async subagents: spawn, report files, and completion wakes."""

from agent_service.subagents.supervisor import (
    MAX_DEPTH,
    MAX_INFLIGHT,
    SPAWN_DESCRIPTION,
    SPAWN_PARAMETERS,
    Supervisor,
)

__all__ = [
    "MAX_DEPTH",
    "MAX_INFLIGHT",
    "SPAWN_DESCRIPTION",
    "SPAWN_PARAMETERS",
    "Supervisor",
]
