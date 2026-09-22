from __future__ import annotations

import asyncio
from typing import Any

import pytest

from research_engine.continuation import CONTINUATION_PROMPT, boundary_overlap
from research_engine.llm.scripted import ScriptedLLM
from research_engine.loop import run_loop
from research_engine.types import ToolCall, TurnResult


class RecordingSeq:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, typ: str, payload: dict | None = None) -> None:
        self.events.append((typ, payload or {}))


class Box:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get(self, name: str):
        async def run(args: dict[str, Any]) -> str:
            self.calls.append({"name": name, **args})
            return "ok"

        return run if name == "record" else None

    def openai_tools(self) -> list[dict[str, Any]]:
        return [{"type": "function", "function": {"name": "record", "parameters": {}}}]


def _joined(seq: RecordingSeq, typ: str) -> str:
    return "".join(str(p.get("delta") or "") for t, p in seq.events if t == typ)


def _completed(seq: RecordingSeq) -> dict:
    return next(p for t, p in seq.events if t == "message.completed")


def _call(cid: str, value: str) -> ToolCall:
    return ToolCall(id=cid, name="record", arguments=f'{{"value":"{value}"}}')


def test_boundary_overlap_is_bounded_and_exact() -> None:
    previous = "x" * 30 + "shared continuation boundary"
    following = "shared continuation boundary and more"
    assert boundary_overlap(previous, following) == len("shared continuation boundary")
    assert boundary_overlap("short", "short and more") == 0
    assert boundary_overlap("alpha", "beta") == 0


@pytest.mark.asyncio
async def test_text_output_limit_continues_once_and_drops_overlap() -> None:
    first = "Alpha beta gamma delta — shared continuation boundary"
    second = " delta — shared continuation boundary and the final sentence."
    expected = "Alpha beta gamma delta — shared continuation boundary and the final sentence."
    llm = ScriptedLLM(
        [
            TurnResult(content=first, finish_reason="length"),
            TurnResult(content=second, finish_reason="stop"),
        ]
    )
    seq = RecordingSeq()
    await run_loop(
        llm=llm,
        tools=Box(),
        messages=[{"role": "user", "content": "go"}],
        seq=seq,
        cancel=asyncio.Event(),
        max_turns=4,
        max_report_chars=10_000,
    )

    assert _joined(seq, "text_delta") == expected
    assert _completed(seq) == {"content": expected, "truncated": False}
    assert seq.events[-1] == ("run.finished", {"status": "succeeded"})
    assert [p["attempt"] for t, p in seq.events if t == "output_continuation"] == [1]
    assert llm.calls[1]["tool_choice"] == "none"
    tail = llm.calls[1]["messages"][-2:]
    assert tail[0]["role"] == "assistant" and tail[0]["content"] == first
    assert tail[1] == {"role": "user", "content": CONTINUATION_PROMPT}
    assert CONTINUATION_PROMPT not in _joined(seq, "text_delta")
    assert CONTINUATION_PROMPT not in _completed(seq)["content"]


@pytest.mark.asyncio
async def test_output_limit_exhaustion_keeps_text_and_marks_truncated() -> None:
    llm = ScriptedLLM(
        [
            TurnResult(content="part one ", finish_reason="length"),
            TurnResult(content="part two ", finish_reason="length"),
            TurnResult(content="part three", finish_reason="length"),
        ]
    )
    seq = RecordingSeq()
    await run_loop(
        llm=llm,
        tools=Box(),
        messages=[{"role": "user", "content": "go"}],
        seq=seq,
        cancel=asyncio.Event(),
        max_turns=4,
        max_report_chars=10_000,
        max_output_continuations=2,
    )

    assert _completed(seq)["content"] == "part one part two part three"
    assert _completed(seq)["truncated"] is True
    assert len([t for t, _ in seq.events if t == "output_continuation"]) == 2
    assert seq.events[-1] == ("run.finished", {"status": "succeeded"})
    assert len([e for e in seq.events if e[0] == "message.completed"]) == 1


@pytest.mark.asyncio
async def test_cancellation_during_continuation_keeps_deduped_text() -> None:
    cancel = asyncio.Event()

    class AbortDuringContinuation:
        model = "scripted"

        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, messages, tools, *, tool_choice="auto", cancel=None, on_delta=None, **_kwargs):
            _ = (messages, tools, tool_choice, cancel)
            self.calls += 1
            if self.calls == 1:
                text = "Alpha beta gamma — shared continuation boundary"
                if on_delta:
                    await on_delta(text)
                return TurnResult(content=text, finish_reason="length")
            text = "shared continuation boundary and kept suffix"
            if on_delta:
                await on_delta(text)
            cancel.set()
            return TurnResult(content=text, finish_reason="length")

    seq = RecordingSeq()
    await run_loop(
        llm=AbortDuringContinuation(),
        tools=Box(),
        messages=[{"role": "user", "content": "go"}],
        seq=seq,
        cancel=cancel,
        max_turns=4,
        max_report_chars=10_000,
    )
    expected = "Alpha beta gamma — shared continuation boundary and kept suffix"
    assert _joined(seq, "text_delta") == expected
    assert _completed(seq)["content"] == expected
    assert seq.events[-1] == ("run.finished", {"status": "cancelled", "error": "cancelled"})


@pytest.mark.asyncio
async def test_truncated_tool_call_is_discarded_then_executed_once() -> None:
    llm = ScriptedLLM(
        [
            TurnResult(content="ignore", tool_calls=[_call("discarded", "no")], finish_reason="length"),
            TurnResult(content="keep", tool_calls=[_call("trusted", "yes")], finish_reason="tool_calls"),
            TurnResult(content="Done."),
        ]
    )
    box = Box()
    seq = RecordingSeq()
    await run_loop(
        llm=llm,
        tools=box,
        messages=[{"role": "user", "content": "go"}],
        seq=seq,
        cancel=asyncio.Event(),
        max_turns=4,
        max_report_chars=10_000,
    )
    assert box.calls == [{"name": "record", "value": "yes"}]
    assert _completed(seq)["content"] == "Done."
    assert seq.events[-1] == ("run.finished", {"status": "succeeded"})
    assert not any(t == "output_continuation" for t, _ in seq.events)


@pytest.mark.asyncio
async def test_repeated_truncated_tool_calls_never_execute() -> None:
    truncated = TurnResult(
        content="",
        tool_calls=[_call("unsafe", "maybe")],
        finish_reason="max_tokens",
    )
    llm = ScriptedLLM([truncated, truncated, truncated])
    box = Box()
    seq = RecordingSeq()
    await run_loop(
        llm=llm,
        tools=box,
        messages=[{"role": "user", "content": "go"}],
        seq=seq,
        cancel=asyncio.Event(),
        max_turns=4,
        max_report_chars=10_000,
    )
    assert box.calls == []
    assert len(llm.calls) == 3
    assert seq.events[-1] == ("run.finished", {"status": "failed", "error": "truncated_tool_call"})
    assert any(t == "error" and p.get("message") == "truncated_tool_call" for t, p in seq.events)
