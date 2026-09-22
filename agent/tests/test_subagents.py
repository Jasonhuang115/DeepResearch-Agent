from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agent_service.config import settings
from agent_service.llm.base import ToolCall, TurnResult
from agent_service.llm.mock import ScriptedLLM
from agent_service.runtime.agent_runner import run_research
from agent_service.subagents.report import report_path, status_path
from agent_service.subagents.supervisor import MAX_DEPTH, MAX_INFLIGHT, Supervisor
from agent_service.tools import default_registry
from agent_service.tools.overflow import Overflow
from agent_service.tools.registry import ToolRegistry
from agent_service.tools.web_search import MockSearcher
from agent_service.workspace.local import LocalProvider
from research_engine.types import LLMClient


class RecordingSeq:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, typ: str, payload: dict | None = None) -> None:
        self.events.append((typ, payload or {}))


class HoldLLM:
    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()

    async def complete(
        self,
        messages: list,
        tools: list,
        *,
        tool_choice: str = "auto",
        cancel: asyncio.Event | None = None,
        on_delta=None,
        on_reasoning=None,
    ) -> TurnResult:
        _ = (messages, tools, tool_choice, on_delta, on_reasoning)
        self.entered.set()
        await self.gate.wait()
        if cancel is not None and cancel.is_set():
            return TurnResult(finish_reason="cancelled")
        return TurnResult(content="done")


class DeltaThenWait(LLMClient):
    async def complete(
        self,
        messages: list,
        tools: list,
        *,
        tool_choice: str = "auto",
        cancel: asyncio.Event | None = None,
        on_delta=None,
        on_reasoning=None,
    ) -> TurnResult:
        _ = (messages, tools, tool_choice, on_reasoning)
        if on_delta is not None:
            await on_delta("partial conclusion")
        for _ in range(400):
            if cancel is not None and cancel.is_set():
                return TurnResult(finish_reason="cancelled")
            await asyncio.sleep(0.01)
        return TurnResult(content="partial conclusion")


def _cmd(question: str, **extra: object) -> dict:
    cmd = {
        "request": {"content": question},
        "messages": [],
        "conversation_id": "conv_spawn",
        "run_id": "run_test",
        "tenant_id": "ten_a",
        "user_id": "usr_a",
    }
    cmd.update(extra)
    return cmd


async def _session(tmp_path: Path, supervisor: Supervisor, conversation_id: str = "conv_1"):
    ws = await LocalProvider(tmp_path).ensure(conversation_id)
    supervisor.note_session(
        conversation_id=conversation_id,
        tenant_id="ten_a",
        user_id="usr_a",
        workspace=ws,
        searcher=MockSearcher(),
    )
    return ws


def _spawn_args(sub_id: str, *, description: str = "find the conclusion", max_time: float = 30) -> dict:
    return {"description": description, "max_time": max_time, "id": sub_id}


async def test_spawn_returns_before_the_child_finishes(tmp_path: Path) -> None:
    hold = HoldLLM()
    wakes: list[dict] = []

    async def publish(payload: dict) -> None:
        wakes.append(payload)

    supervisor = Supervisor(publish_wake=publish, llm_factory=lambda: hold)
    ws = await _session(tmp_path, supervisor)
    try:
        out = await supervisor.spawn("conv_1", 0, _spawn_args("alpha"))
        assert "status=running" in out
        assert "subagents/alpha/report.md" in out
        assert not hold.gate.is_set()
        await hold.entered.wait()
        assert await ws.read_text("subagents/alpha/spec.md") == "find the conclusion"
        status = json.loads(await ws.read_text(status_path("alpha")))
        assert status["status"] == "running"
        hold.gate.set()
        await supervisor.settle()
    finally:
        hold.gate.set()
        await supervisor.cancel_conversation("conv_1")
        await supervisor.settle()

    assert wakes == [
        {
            "v": 1,
            "conversation_id": "conv_1",
            "tenant_id": "ten_a",
            "user_id": "usr_a",
            "id": "alpha",
            "status": "succeeded",
            "report_path": "subagents/alpha/report.md",
        }
    ]
    assert "done" in await ws.read_text(report_path("alpha"))
    assert json.loads(await ws.read_text(status_path("alpha")))["status"] == "succeeded"


async def test_spawn_rejects_bad_args_depth_and_duplicates(tmp_path: Path) -> None:
    supervisor = Supervisor(llm_factory=lambda: HoldLLM())
    await _session(tmp_path, supervisor)
    assert "description" in await supervisor.spawn("conv_1", 0, {"description": "  ", "max_time": 5, "id": "a"})
    assert "max_time" in await supervisor.spawn("conv_1", 0, {"description": "task", "max_time": 0, "id": "a"})
    assert "max_time" in await supervisor.spawn("conv_1", 0, {"description": "task", "max_time": "30", "id": "a"})
    assert "id must match" in await supervisor.spawn("conv_1", 0, {"description": "task", "max_time": 5, "id": "bad id"})
    assert "spawn depth exceeded" in await supervisor.spawn("conv_1", MAX_DEPTH, _spawn_args("too-deep"))

    hold = HoldLLM()
    supervisor._llm_factory = lambda: hold
    try:
        first = await supervisor.spawn("conv_1", 0, _spawn_args("alpha"))
        assert first.startswith("spawned")
        again = await supervisor.spawn("conv_1", 0, _spawn_args("alpha"))
        assert "already exists" in again
    finally:
        hold.gate.set()
        await supervisor.cancel_conversation("conv_1")
        await supervisor.settle()


async def test_inflight_cap_rejects_the_next_spawn(tmp_path: Path) -> None:
    hold = HoldLLM()
    supervisor = Supervisor(llm_factory=lambda: hold)
    await _session(tmp_path, supervisor)
    try:
        for n in range(MAX_INFLIGHT):
            out = await supervisor.spawn("conv_1", 0, _spawn_args(f"n{n}"))
            assert out.startswith("spawned"), out
        blocked = await supervisor.spawn("conv_1", 0, _spawn_args("overflow"))
        assert "too many subagents" in blocked
    finally:
        hold.gate.set()
        await supervisor.cancel_conversation("conv_1")
        await supervisor.settle()


async def test_many_turns_are_not_cut_by_max_turns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_turns", 1)
    seen: list[int] = []

    async def probe(_args: dict) -> str:
        seen.append(1)
        return "probe-ok"

    def factory(job, workspace, session):
        _ = session
        registry = ToolRegistry()
        registry.overflow = Overflow(workspace, run_id=job.sub_id, always_store=True)
        registry.register("probe", probe, description="probe", parameters={"type": "object", "properties": {}})
        return registry

    turns: list[TurnResult] = [
        TurnResult(content=f"step {n}", tool_calls=[ToolCall(id=f"p{n}", name="probe", arguments="{}")])
        for n in range(9)
    ]
    turns.append(TurnResult(content="ALL_TURNS_DONE"))
    supervisor = Supervisor(llm_factory=lambda: ScriptedLLM(turns), registry_factory=factory)
    ws = await _session(tmp_path, supervisor)
    out = await supervisor.spawn("conv_1", 0, _spawn_args("long"))
    assert out.startswith("spawned")
    await supervisor.settle()
    assert len(seen) == 9
    report = await ws.read_text(report_path("long"))
    assert report == "ALL_TURNS_DONE"
    assert "step 0" not in report
    assert json.loads(await ws.read_text(status_path("long")))["status"] == "succeeded"


async def test_report_keeps_conclusions_and_stores_tool_bodies(tmp_path: Path) -> None:
    def factory(job, workspace, session):
        _ = session
        registry = default_registry(
            workspace,
            overflow=Overflow(workspace, run_id=job.sub_id, max_chars=10000, always_store=True),
            searcher=MockSearcher(),
        )

        async def probe(_args: dict) -> str:
            return "TOOL_BODY_MARKER"

        registry.register("probe", probe, description="probe", parameters={"type": "object", "properties": {}})
        return registry

    llm = ScriptedLLM(
        [
            TurnResult(content="THINKING_MARKER", tool_calls=[ToolCall(id="p1", name="probe", arguments="{}")]),
            TurnResult(
                content="SEARCH_THOUGHT",
                tool_calls=[ToolCall(id="s1", name="web_search", arguments='{"query":"solid"}')],
            ),
            TurnResult(content="CONCLUSION_MARKER"),
        ]
    )
    supervisor = Supervisor(llm_factory=lambda: llm, registry_factory=factory)
    ws = await _session(tmp_path, supervisor)
    await supervisor.spawn("conv_1", 0, _spawn_args("reader"))
    await supervisor.settle()
    report = await ws.read_text(report_path("reader"))
    assert report == "CONCLUSION_MARKER"
    assert "THINKING_MARKER" not in report
    assert "SEARCH_THOUGHT" not in report
    assert "TOOL_BODY_MARKER" not in report
    assert "Mock excerpt" not in report
    assert await ws.read_text("tool-output/reader/p1.txt") == "TOOL_BODY_MARKER"
    names = await ws.list_files("tool-output/reader/**")
    assert "tool-output/reader/s1.txt" not in names


async def test_conclusion_is_written_before_the_loop_ends(tmp_path: Path) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class StreamHold:
        async def complete(
            self,
            messages: list,
            tools: list,
            *,
            tool_choice: str = "auto",
            cancel: asyncio.Event | None = None,
            on_delta=None,
            on_reasoning=None,
        ) -> TurnResult:
            _ = (messages, tools, tool_choice, on_reasoning, cancel)
            if on_delta is not None:
                await on_delta("early conclusion")
            started.set()
            await release.wait()
            return TurnResult(content="early conclusion")

    supervisor = Supervisor(llm_factory=lambda: StreamHold())
    ws = await _session(tmp_path, supervisor)
    try:
        await supervisor.spawn("conv_1", 0, _spawn_args("live"))
        await started.wait()
        assert await ws.read_text(report_path("live")) == "early conclusion"
        assert json.loads(await ws.read_text(status_path("live")))["status"] == "running"
    finally:
        release.set()
        await supervisor.settle()


async def test_max_time_is_the_only_backstop(tmp_path: Path) -> None:
    wakes: list[dict] = []

    async def publish(payload: dict) -> None:
        wakes.append(payload)

    supervisor = Supervisor(publish_wake=publish, llm_factory=lambda: DeltaThenWait())
    ws = await _session(tmp_path, supervisor)
    await supervisor.spawn("conv_1", 0, _spawn_args("slow", max_time=0.2))
    await supervisor.settle()
    report = await ws.read_text(report_path("slow"))
    assert "partial conclusion" in report
    assert json.loads(await ws.read_text(status_path("slow")))["status"] == "timed_out"
    assert wakes[0]["status"] == "timed_out"
    assert wakes[0]["report_path"] == "subagents/slow/report.md"


async def test_cancel_does_not_wake(tmp_path: Path) -> None:
    hold = HoldLLM()
    wakes: list[dict] = []

    async def publish(payload: dict) -> None:
        wakes.append(payload)

    supervisor = Supervisor(publish_wake=publish, llm_factory=lambda: hold)
    ws = await _session(tmp_path, supervisor)
    await supervisor.spawn("conv_1", 0, _spawn_args("stop-me"))
    await hold.entered.wait()
    await supervisor.cancel_conversation("conv_1")
    hold.gate.set()
    await supervisor.settle()
    assert wakes == []
    assert json.loads(await ws.read_text(status_path("stop-me")))["status"] == "cancelled"


async def test_grandchild_can_spawn_and_cannot_spawn_further(tmp_path: Path) -> None:
    tool_names: list[list[str]] = []
    grand = ScriptedLLM([TurnResult(content="GRAND_CONCLUSION")])
    child = ScriptedLLM(
        [
            TurnResult(
                content="dispatch grandchild",
                tool_calls=[
                    ToolCall(
                        id="g1",
                        name="spawn_subagent",
                        arguments=json.dumps(_spawn_args("grand")),
                    )
                ],
            ),
            TurnResult(content="CHILD_CONCLUSION"),
        ]
    )
    queue: list[ScriptedLLM] = [child, grand]

    class RecordingGrand:
        async def complete(
            self,
            messages: list,
            tools: list,
            *,
            tool_choice: str = "auto",
            cancel: asyncio.Event | None = None,
            on_delta=None,
            on_reasoning=None,
        ) -> TurnResult:
            tool_names.append([item["function"]["name"] for item in tools])
            return await grand.complete(
                messages,
                tools,
                tool_choice=tool_choice,
                cancel=cancel,
                on_delta=on_delta,
                on_reasoning=on_reasoning,
            )

    def factory() -> object:
        nxt = queue.pop(0)
        if nxt is grand:
            return RecordingGrand()
        return nxt

    supervisor = Supervisor(llm_factory=factory)  # type: ignore[arg-type]
    ws = await _session(tmp_path, supervisor)
    await supervisor.spawn("conv_1", 0, _spawn_args("child"))
    await supervisor.settle()
    assert await ws.read_text(report_path("child")) == "CHILD_CONCLUSION"
    assert "dispatch grandchild" not in await ws.read_text(report_path("child"))
    assert await ws.read_text(report_path("grand")) == "GRAND_CONCLUSION"
    assert tool_names and "spawn_subagent" not in tool_names[0]
    assert json.loads(await ws.read_text(status_path("grand")))["depth"] == 2


async def test_two_finished_subagents_each_publish_a_wake(tmp_path: Path) -> None:
    wakes: list[dict] = []

    async def publish(payload: dict) -> None:
        wakes.append(payload)

    llms = [
        ScriptedLLM([TurnResult(content="A done")]),
        ScriptedLLM([TurnResult(content="B done")]),
    ]

    def factory() -> ScriptedLLM:
        return llms.pop(0)

    supervisor = Supervisor(publish_wake=publish, llm_factory=factory)
    await _session(tmp_path, supervisor)
    await supervisor.spawn("conv_1", 0, _spawn_args("alpha"))
    await supervisor.spawn("conv_1", 0, _spawn_args("beta"))
    await supervisor.settle()
    assert {item["id"] for item in wakes} == {"alpha", "beta"}
    assert {item["report_path"] for item in wakes} == {
        "subagents/alpha/report.md",
        "subagents/beta/report.md",
    }


async def test_wake_run_exposes_report_paths_in_system_context() -> None:
    llm = ScriptedLLM([TurnResult(content="Sulfide leads.")])
    seq = RecordingSeq()
    cmd = _cmd(
        "",
        messages=[{"id": "msg_1", "role": "user", "content": "固态电池怎么样"}],
        wake={
            "reports": [
                {"id": "alpha", "status": "succeeded", "report_path": "subagents/alpha/report.md"},
                {"id": "beta", "status": "timed_out", "report_path": "subagents/beta/report.md"},
            ]
        },
    )
    await run_research(cmd, seq, asyncio.Event(), llm=llm, tools=ToolRegistry())
    system = llm.calls[0]["messages"][0]["content"]
    assert "<subagent-reports>" in system
    assert "subagents/alpha/report.md" in system
    assert "subagents/beta/report.md" in system
    users = [m["content"] for m in llm.calls[0]["messages"] if m["role"] == "user"]
    assert any("阅读系统上下文" in text for text in users)
    assert seq.events[-2][0] == "message.completed"
    assert seq.events[-2][1]["content"] == "Sulfide leads."
    assert "subagents/alpha/report.md" not in seq.events[-2][1]["content"]


async def test_main_run_spawn_does_not_stream_the_child_into_chat(tmp_path: Path) -> None:
    release = asyncio.Event()
    started = asyncio.Event()

    class Hold:
        async def complete(
            self,
            messages: list,
            tools: list,
            *,
            tool_choice: str = "auto",
            cancel: asyncio.Event | None = None,
            on_delta=None,
            on_reasoning=None,
        ) -> TurnResult:
            _ = (messages, tools, tool_choice, on_reasoning)
            started.set()
            await release.wait()
            if cancel is not None and cancel.is_set():
                return TurnResult(finish_reason="cancelled")
            if on_delta is not None:
                await on_delta("child done")
            return TurnResult(content="child done")

    wakes: list[dict] = []

    async def publish(payload: dict) -> None:
        wakes.append(payload)

    supervisor = Supervisor(publish_wake=publish, llm_factory=lambda: Hold())
    parent = ScriptedLLM(
        [
            TurnResult(
                tool_calls=[
                    ToolCall(id="s1", name="spawn_subagent", arguments=json.dumps(_spawn_args("alpha")))
                ]
            ),
            TurnResult(content="Dispatched."),
        ]
    )
    seq = RecordingSeq()
    try:
        await run_research(
            _cmd("go"),
            seq,
            asyncio.Event(),
            llm=parent,
            supervisor=supervisor,
            workspace_provider=LocalProvider(tmp_path),
        )
        summaries = [p.get("summary") or "" for t, p in seq.events if t == "tool_call.finished"]
        assert any("status=running" in text for text in summaries)
        assert seq.events[-2] == ("message.completed", {"content": "Dispatched.", "truncated": False})
        chat = "".join(str(p.get("delta") or "") for t, p in seq.events if t == "text_delta")
        assert "child done" not in chat
        await started.wait()
    finally:
        release.set()
        await supervisor.settle()
    assert wakes and wakes[0]["id"] == "alpha"
    assert wakes[0]["status"] == "succeeded"
