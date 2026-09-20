from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent_service.llm.base import ToolCall, TurnResult
from agent_service.llm.mock import ScriptedLLM
from agent_service.runtime.agent_runner import run_research
from agent_service.tools.web_search import MockSearcher
from agent_service.workspace.local import LocalProvider


class RecordingSeq:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, typ: str, payload: dict | None = None) -> None:
        self.events.append((typ, payload or {}))


def _cmd(question: str = "research batteries") -> dict:
    return {
        "request": {"content": question},
        "messages": [],
        "conversation_id": "conv_web",
        "run_id": "run_web",
    }


@pytest.mark.asyncio
async def test_run_research_search_uses_workspace_ledger(tmp_path: Path) -> None:
    llm = ScriptedLLM(
        [
            TurnResult(
                content="search",
                tool_calls=[ToolCall(id="c1", name="web_search", arguments='{"query":"sulfide"}')],
            ),
            TurnResult(content="done with mock hits"),
        ]
    )
    seq = RecordingSeq()
    await run_research(
        _cmd(),
        seq,
        asyncio.Event(),
        llm=llm,
        workspace_provider=LocalProvider(tmp_path),
        searcher=MockSearcher(),
    )
    assert seq.events[-1] == ("run.finished", {"status": "succeeded"})
    finished = [p for t, p in seq.events if t == "tool_call.finished"]
    assert finished[0]["ok"] is True
    assert "src_01" in finished[0]["summary"]
    assert not any(t == "source.added" for t, _ in seq.events)
    ledger = (tmp_path / "conv_web" / "sources" / "ledger.json").read_text(encoding="utf-8")
    assert "sulfide" in ledger
