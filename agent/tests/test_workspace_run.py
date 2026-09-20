from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent_service.config import settings
from agent_service.llm.base import ToolCall, TurnResult
from agent_service.llm.mock import ScriptedLLM
from agent_service.runtime.agent_runner import run_research
from agent_service.workspace.e2b import FakeE2BFactory, LOST_NOTICE
from agent_service.workspace.local import LocalProvider
from agent_service.workspace.provider import build_provider
from agent_service.workspace.store import MemorySandboxIdStore


class RecordingSeq:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, typ: str, payload: dict | None = None) -> None:
        self.events.append((typ, payload or {}))


def _cmd(question: str = "q") -> dict:
    return {
        "request": {"content": question},
        "messages": [],
        "conversation_id": "conv_test",
        "run_id": "run_test",
    }


@pytest.mark.asyncio
async def test_run_research_write_then_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "workspace_mode", "local")
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    monkeypatch.setattr(settings, "e2b_api_key", "")
    llm = ScriptedLLM(
        [
            TurnResult(
                content="write",
                tool_calls=[
                    ToolCall(id="c1", name="Write", arguments='{"path":"a.md","content":"hello"}')
                ],
            ),
            TurnResult(
                content="read",
                tool_calls=[ToolCall(id="c2", name="Read", arguments='{"path":"a.md"}')],
            ),
            TurnResult(content="saw hello"),
        ]
    )
    seq = RecordingSeq()
    await run_research(
        _cmd(),
        seq,
        asyncio.Event(),
        llm=llm,
        workspace_provider=LocalProvider(tmp_path),
    )
    assert (tmp_path / "conv_test" / "a.md").read_text(encoding="utf-8") == "hello"
    finished = [p for t, p in seq.events if t == "tool_call.finished"]
    assert finished[0]["ok"] is True
    assert "hello" in finished[1]["summary"]
    assert seq.events[-1] == ("run.finished", {"status": "succeeded"})


@pytest.mark.asyncio
async def test_run_research_includes_lost_workspace_notice(tmp_path: Path) -> None:
    factory = FakeE2BFactory()
    store = MemorySandboxIdStore()
    await store.set("conv_test", "sb_missing")
    factory.fail_connect = True
    provider = build_provider(
        mode="e2b",
        e2b_api_key="ek",
        factory=factory,
        store=store,
        workspace_root=str(tmp_path),
    )
    llm = ScriptedLLM([TurnResult(content="ok")])
    seq = RecordingSeq()
    await run_research(_cmd(), seq, asyncio.Event(), llm=llm, workspace_provider=provider)
    system = llm.calls[0]["messages"][0]["content"]
    assert LOST_NOTICE in system
    assert "<workspace>" in system
