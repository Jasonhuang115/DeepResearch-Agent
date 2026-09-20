from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from research_engine.completion import FinishKind, normalize_finish
from research_engine.types import EventEmitter, LLMClient, ToolBox, ToolCall, TurnResult

log = logging.getLogger("research_engine.loop")

EMPTY_FINAL = "empty final response"


async def run_loop(
    *,
    llm: LLMClient,
    tools: ToolBox,
    messages: list[dict[str, Any]],
    seq: EventEmitter,
    cancel: asyncio.Event,
    max_turns: int,
    max_report_chars: int,
    prepare_messages: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
) -> None:
    notes: list[str] = []
    openai_tools = tools.openai_tools()
    prepare = prepare_messages or (lambda m: m)

    try:
        for turn in range(1, max_turns + 1):
            if cancel.is_set():
                await _finish(seq, "cancelled", _partial(notes), "cancelled")
                return
            done = await _step(
                llm,
                tools,
                openai_tools,
                messages,
                seq,
                cancel,
                notes,
                turn=turn,
                tool_choice="auto",
                max_report_chars=max_report_chars,
                prepare=prepare,
            )
            if done:
                return

        if cancel.is_set():
            await _finish(seq, "cancelled", _partial(notes), "cancelled")
            return
        result = await _complete(
            llm, messages, openai_tools, "none", cancel, seq, max_turns + 1, notes, prepare
        )
        if result is None:
            return
        await _handle_final(seq, result, cancel, notes, max_report_chars, streamed=False)
    except Exception as exc:  # noqa: BLE001
        log.exception("run failed")
        await seq.emit("error", {"message": str(exc)})
        await _finish(seq, "failed", _partial(notes), str(exc))


async def _step(
    llm: LLMClient,
    tools: ToolBox,
    openai_tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    seq: EventEmitter,
    cancel: asyncio.Event,
    notes: list[str],
    *,
    turn: int,
    tool_choice: str,
    max_report_chars: int,
    prepare: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> bool:
    streamed: list[str] = []

    async def on_delta(piece: str) -> None:
        streamed.append(piece)
        await seq.emit("text_delta", {"delta": piece})

    async def on_reasoning(piece: str) -> None:
        await seq.emit("reasoning_delta", {"delta": piece})

    result = await _complete(
        llm,
        messages,
        openai_tools,
        tool_choice,
        cancel,
        seq,
        turn,
        notes,
        prepare,
        on_delta=on_delta,
        on_reasoning=on_reasoning,
    )
    if result is None:
        return True

    info = normalize_finish(
        result.finish_reason,
        has_tool_calls=bool(result.tool_calls),
        cancelled=cancel.is_set(),
    )
    if info.kind == FinishKind.CANCELLED or cancel.is_set():
        await _finish(seq, "cancelled", _partial(notes) or "".join(streamed), "cancelled")
        return True
    if info.kind in (FinishKind.FILTERED, FinishKind.ERROR, FinishKind.UNKNOWN):
        msg = info.provider_reason or info.kind.value
        await seq.emit("error", {"message": msg})
        await _finish(seq, "failed", _partial(notes) or "".join(streamed), msg)
        return True
    if result.tool_calls:
        if streamed:
            # live path already sent answer tokens; keep a reasoning copy for tool turns
            pass
        if result.content:
            notes.append(result.content)
            if not streamed:
                await _delta(seq, "reasoning_delta", result.content)
        cancelled = await _run_tools(tools, result, messages, seq, cancel, notes)
        return cancelled
    await _handle_final(
        seq,
        result,
        cancel,
        notes,
        max_report_chars,
        streamed=bool(streamed),
        streamed_text="".join(streamed),
    )
    return True


async def _complete(
    llm: LLMClient,
    messages: list[dict[str, Any]],
    openai_tools: list[dict[str, Any]],
    tool_choice: str,
    cancel: asyncio.Event,
    seq: EventEmitter,
    turn: int,
    notes: list[str],
    prepare: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    on_delta: Any = None,
    on_reasoning: Any = None,
) -> TurnResult | None:
    await seq.emit("run.progress", {"turn": turn, "note": "thinking"})
    window = prepare(messages)

    async def emit_reasoning(piece: str) -> None:
        await seq.emit("reasoning_delta", {"delta": piece})

    result = await llm.complete(
        window,
        openai_tools,
        tool_choice=tool_choice,
        cancel=cancel,
        on_delta=on_delta,
        on_reasoning=on_reasoning or emit_reasoning,
    )
    if cancel.is_set():
        await _finish(seq, "cancelled", _partial(notes), "cancelled")
        return None
    return result


async def _run_tools(
    tools: ToolBox,
    result: TurnResult,
    messages: list[dict[str, Any]],
    seq: EventEmitter,
    cancel: asyncio.Event,
    notes: list[str],
) -> bool:
    messages.append(
        {
            "role": "assistant",
            "content": result.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments or "{}"},
                }
                for call in result.tool_calls
            ],
        }
    )
    rows = await asyncio.gather(*[_invoke(tools, call, seq, cancel) for call in result.tool_calls])
    for call, _ok, text in rows:
        messages.append({"role": "tool", "tool_call_id": call.id, "content": text})
    if cancel.is_set():
        await _finish(seq, "cancelled", _partial(notes), "cancelled")
        return True
    return False


async def _invoke(
    tools: ToolBox,
    call: ToolCall,
    seq: EventEmitter,
    cancel: asyncio.Event,
) -> tuple[ToolCall, bool, str]:
    args = _parse_args(call.arguments)
    await seq.emit(
        "tool_call.started",
        {"tool_call_id": call.id, "name": call.name, "args": args},
    )
    if cancel.is_set():
        await seq.emit("tool_call.finished", {"tool_call_id": call.id, "ok": False, "summary": "cancelled"})
        return call, False, "cancelled"

    fn = tools.get(call.name)
    if fn is None:
        err = f"unknown tool: {call.name}"
        await seq.emit("tool_call.finished", {"tool_call_id": call.id, "ok": False, "summary": err})
        return call, False, err

    try:
        text = await fn(args)
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
        await seq.emit("tool_call.finished", {"tool_call_id": call.id, "ok": False, "summary": err})
        return call, False, err

    if cancel.is_set():
        await seq.emit("tool_call.finished", {"tool_call_id": call.id, "ok": False, "summary": "cancelled"})
        return call, False, "cancelled"

    await seq.emit("tool_call.finished", {"tool_call_id": call.id, "ok": True, "summary": text[:180]})
    return call, True, text


async def _handle_final(
    seq: EventEmitter,
    result: TurnResult,
    cancel: asyncio.Event,
    notes: list[str],
    max_report_chars: int,
    *,
    streamed: bool,
    streamed_text: str = "",
) -> None:
    text = streamed_text or result.content or ""
    truncated = False
    if len(text) > max_report_chars:
        text = text[:max_report_chars]
        truncated = True
    if cancel.is_set():
        await _finish(seq, "cancelled", text or _partial(notes), "cancelled")
        return
    info = normalize_finish(
        result.finish_reason,
        has_tool_calls=False,
        cancelled=False,
    )
    if info.kind == FinishKind.OUTPUT_LIMIT:
        truncated = True
    if not text.strip():
        await seq.emit("error", {"message": EMPTY_FINAL})
        await _finish(seq, "failed", _partial(notes), EMPTY_FINAL)
        return
    if not streamed:
        for chunk in _chunks(text, 24):
            if cancel.is_set():
                await _finish(seq, "cancelled", text, "cancelled")
                return
            await seq.emit("text_delta", {"delta": chunk})
    await seq.emit("message.completed", {"content": text, "truncated": truncated})
    await seq.emit("run.finished", {"status": "succeeded"})


async def _finish(seq: EventEmitter, status: str, content: str, error: str | None) -> None:
    await seq.emit("message.completed", {"content": content, "truncated": False})
    payload: dict[str, Any] = {"status": status}
    if error:
        payload["error"] = error
    await seq.emit("run.finished", payload)


async def _delta(seq: EventEmitter, typ: str, text: str) -> None:
    for chunk in _chunks(text, 40):
        await seq.emit(typ, {"delta": chunk})


def _chunks(text: str, n: int) -> list[str]:
    if not text:
        return []
    return [text[i : i + n] for i in range(0, len(text), n)]


def _partial(notes: list[str]) -> str:
    return "\n\n".join(n for n in notes if n)


def _parse_args(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return val if isinstance(val, dict) else {}
