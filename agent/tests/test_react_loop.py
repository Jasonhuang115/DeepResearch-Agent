from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent_service.config import settings
from agent_service.llm.base import ToolCall, TurnResult
from agent_service.llm.mock import ScriptedLLM
from agent_service.runtime.agent_runner import MISSING_KEY, run_research
from agent_service.tools.registry import ToolRegistry
from agent_service.tools.web_search import DESCRIPTION, PARAMETERS
from research_engine.loop import EMPTY_FINAL


class RecordingSeq:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, typ: str, payload: dict | None = None) -> None:
        self.events.append((typ, payload or {}))


def _types(seq: RecordingSeq) -> list[str]:
    return [t for t, _ in seq.events]


def _joined(seq: RecordingSeq, typ: str) -> str:
    return "".join(str(p.get("delta") or "") for t, p in seq.events if t == typ)


def _payloads(seq: RecordingSeq, typ: str) -> list[dict]:
    return [p for t, p in seq.events if t == typ]


def _cmd(question: str, history: list[dict] | None = None) -> dict:
    return {
        "request": {"content": question},
        "messages": history or [],
        "conversation_id": "conv_test",
        "run_id": "run_test",
    }


async def _instant_search(args: dict[str, Any]) -> str:
    return f"results for {args.get('query')}"


def _search_registry(fn=_instant_search) -> ToolRegistry:
    r = ToolRegistry()
    r.register("web_search", fn, description=DESCRIPTION, parameters=PARAMETERS)
    return r


def _call(n: int, query: str, name: str = "web_search") -> ToolCall:
    return ToolCall(id=f"c{n}", name=name, arguments=f'{{"query":"{query}"}}')


@pytest.mark.asyncio
async def test_two_searches_then_report() -> None:
    llm = ScriptedLLM(
        [
            TurnResult(content="Map families.", tool_calls=[_call(1, "sulfide families")]),
            TurnResult(content="Compare routes.", tool_calls=[_call(2, "oxide vs sulfide")]),
            TurnResult(content="# Report\nSulfide leads near term."),
        ]
    )
    seq = RecordingSeq()
    await run_research(_cmd("solid-state electrolytes"), seq, asyncio.Event(), llm=llm, tools=_search_registry())

    assert _types(seq)[0] == "run.started"
    assert seq.events[0][1]["model"] == "scripted"
    assert _joined(seq, "reasoning_delta") == "Map families.Compare routes."
    assert _joined(seq, "text_delta") == "# Report\nSulfide leads near term."
    assert [p["name"] for p in _payloads(seq, "tool_call.started")] == ["web_search", "web_search"]
    assert all(p["ok"] for p in _payloads(seq, "tool_call.finished"))
    assert seq.events[-2] == ("message.completed", {"content": "# Report\nSulfide leads near term.", "truncated": False})
    assert seq.events[-1] == ("run.finished", {"status": "succeeded"})

    assert llm.calls[0]["tool_choice"] == "auto"
    last_msgs = llm.calls[2]["messages"]
    roles = [m["role"] for m in last_msgs]
    assert roles.count("tool") == 2
    assert last_msgs[-1]["role"] == "tool"
    assert "results for oxide vs sulfide" in last_msgs[-1]["content"]
    assert "<role>" in last_msgs[0]["content"]
    assert "conv_test" in last_msgs[0]["content"]


@pytest.mark.asyncio
async def test_cancel_mid_loop() -> None:
    cancel = asyncio.Event()

    async def stop(_args: dict[str, Any]) -> str:
        cancel.set()
        return "partial"

    llm = ScriptedLLM(
        [
            TurnResult(content="Searching.", tool_calls=[_call(1, "q")]),
            TurnResult(content="should not run"),
        ]
    )
    seq = RecordingSeq()
    await run_research(_cmd("question"), seq, cancel, llm=llm, tools=_search_registry(stop))

    assert len(llm.calls) == 1
    assert seq.events[-1][1]["status"] == "cancelled"
    assert seq.events[-2][0] == "message.completed"
    assert "tool_call.started" in _types(seq)
    finished = _payloads(seq, "tool_call.finished")
    assert finished and finished[0]["ok"] is False
    assert "run.finished" in _types(seq)
    assert "text_delta" not in _types(seq)


@pytest.mark.asyncio
async def test_unknown_tool_then_recover() -> None:
    llm = ScriptedLLM(
        [
            TurnResult(content="Try a bad tool.", tool_calls=[_call(1, "q", name="nope")]),
            TurnResult(content="# Report\nRecovered."),
        ]
    )
    seq = RecordingSeq()
    await run_research(_cmd("question"), seq, asyncio.Event(), llm=llm, tools=_search_registry())

    finished = _payloads(seq, "tool_call.finished")
    assert finished[0]["ok"] is False
    assert "unknown tool: nope" in finished[0]["summary"]
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.get("role") == "tool"]
    assert tool_msgs and "unknown tool: nope" in tool_msgs[0]["content"]
    assert seq.events[-1] == ("run.finished", {"status": "succeeded"})
    assert _joined(seq, "text_delta") == "# Report\nRecovered."


@pytest.mark.asyncio
async def test_max_turns_forces_tool_choice_none() -> None:
    class AlwaysSearch:
        model = "scripted"

        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def complete(self, messages, tools, *, tool_choice="auto", cancel=None, on_delta=None, **_kwargs):
            self.calls.append({"tool_choice": tool_choice, "messages": messages})
            if tool_choice == "none":
                return TurnResult(content="# Report\nForced stop.")
            n = len(self.calls)
            return TurnResult(content=f"search {n}", tool_calls=[_call(n, "q")])

    llm = AlwaysSearch()
    seq = RecordingSeq()
    await run_research(
        _cmd("question"),
        seq,
        asyncio.Event(),
        llm=llm,
        tools=_search_registry(),
        max_turns=1,
    )

    assert [c["tool_choice"] for c in llm.calls] == ["auto", "none"]
    assert seq.events[-1] == ("run.finished", {"status": "succeeded"})
    assert _joined(seq, "text_delta") == "# Report\nForced stop."
    assert _payloads(seq, "run.progress")[-1]["turn"] == 2


@pytest.mark.asyncio
async def test_max_turns_empty_final_fails() -> None:
    class EmptyNone:
        model = "scripted"

        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def complete(self, messages, tools, *, tool_choice="auto", cancel=None, on_delta=None, **_kwargs):
            self.calls.append({"tool_choice": tool_choice})
            if tool_choice == "none":
                return TurnResult()
            return TurnResult(content="go", tool_calls=[_call(1, "q")])

    seq = RecordingSeq()
    await run_research(
        _cmd("question"),
        seq,
        asyncio.Event(),
        llm=EmptyNone(),
        tools=_search_registry(),
        max_turns=1,
    )
    assert seq.events[-1][1]["status"] == "failed"
    assert seq.events[-1][1]["error"] == EMPTY_FINAL
    assert any(t == "error" for t, _ in seq.events)


@pytest.mark.asyncio
async def test_missing_api_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", "")
    seq = RecordingSeq()
    await run_research(_cmd("question"), seq, asyncio.Event())
    assert seq.events[0][0] == "run.started"
    assert any(t == "error" and p.get("message") == MISSING_KEY for t, p in seq.events)
    assert seq.events[-1] == ("run.finished", {"status": "failed", "error": MISSING_KEY})


@pytest.mark.asyncio
async def test_history_not_duplicated() -> None:
    llm = ScriptedLLM([TurnResult(content="done")])
    seq = RecordingSeq()
    await run_research(
        _cmd("hello", [{"role": "user", "content": "hello"}]),
        seq,
        asyncio.Event(),
        llm=llm,
        tools=_search_registry(),
    )
    roles_contents = [(m["role"], m["content"]) for m in llm.calls[0]["messages"]]
    assert roles_contents.count(("user", "hello")) == 1
    assert roles_contents[0][0] == "system"


@pytest.mark.asyncio
async def test_tool_exception_does_not_crash_run() -> None:
    async def boom(_args: dict[str, Any]) -> str:
        raise RuntimeError("search down")

    llm = ScriptedLLM(
        [
            TurnResult(content="search", tool_calls=[_call(1, "q")]),
            TurnResult(content="answered anyway"),
        ]
    )
    seq = RecordingSeq()
    await run_research(_cmd("q"), seq, asyncio.Event(), llm=llm, tools=_search_registry(boom))
    finished = _payloads(seq, "tool_call.finished")
    assert finished[0]["ok"] is False
    assert "search down" in finished[0]["summary"]
    assert seq.events[-1] == ("run.finished", {"status": "succeeded"})


@pytest.mark.asyncio
async def test_openai_tools_schema() -> None:
    tools = _search_registry().openai_tools()
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "web_search"
    assert "query" in tools[0]["function"]["parameters"]["required"]
