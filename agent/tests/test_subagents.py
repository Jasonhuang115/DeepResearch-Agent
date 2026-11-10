from __future__ import annotations

import asyncio
from types import MethodType

import pytest

from agent_service.subagents.report import report_path
from agent_service.subagents.supervisor import Supervisor
from agent_service.workspace.local import LocalProvider


class Events:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict]] = []

    async def emit(self, typ: str, payload: dict | None = None) -> None:
        self.items.append((typ, payload or {}))


@pytest.mark.asyncio
async def test_subagent_is_one_level_and_parent_waits(tmp_path) -> None:
    workspace = await LocalProvider(tmp_path).ensure("conversation")
    supervisor = Supervisor()
    supervisor.note_session(conversation_id="conversation", workspace=workspace)
    events = Events()

    async def fake_drive(self: Supervisor, job) -> None:
        await asyncio.sleep(0.01)
        await workspace.write_text(report_path(job.sub_id), "finished report")
        await self._finish(job, "succeeded")

    supervisor._drive = MethodType(fake_drive, supervisor)
    result = await supervisor.spawn(
        "conversation",
        0,
        {"id": "child", "description": "research", "max_time": 10},
        parent_emitter=events,
    )

    assert result == "finished report"
    assert [item[0] for item in events.items] == [
        "subagent.started",
        "subagent.finished",
    ]
    assert (
        await supervisor.spawn(
            "conversation",
            1,
            {"id": "grandchild", "description": "no", "max_time": 10},
        )
        == "error: spawn depth exceeded"
    )
