from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from research_engine.completion import FinishKind, normalize_finish
from research_engine.trace import NullTracer, result_overflowed, tool_input, usage_dict
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
    max_turns: int | None,
    max_report_chars: int,
    prepare_messages: Callable[
        [list[dict[str, Any]]], list[dict[str, Any]] | Awaitable[list[dict[str, Any]]]
    ]
    | None = None,
    tracer: Any | None = None,
) -> None:
    notes: list[str] = []
    openai_tools = tools.openai_tools()
    prepare = prepare_messages or (lambda m: m)
    trace = tracer or NullTracer()

    try:
        turn = 0
        while True:
            turn += 1
            if max_turns is not None and turn > max_turns:
                break
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
                tracer=trace,
            )
            if done:
                return

        if max_turns is None:
            return
        if cancel.is_set():
            await _finish(seq, "cancelled", _partial(notes), "cancelled")
            return
        trace.add_turn()
        with trace.span("turn", turn=max_turns + 1):
            result = await _complete(
                llm,
                messages,
                openai_tools,
                "none",
                cancel,
                seq,
                max_turns + 1,
                notes,
                prepare,
                tracer=trace,
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
    prepare: Callable[
        [list[dict[str, Any]]], list[dict[str, Any]] | Awaitable[list[dict[str, Any]]]
    ],
    tracer: Any,
) -> bool:
    tracer.add_turn()
    with tracer.span("turn", turn=turn):
        return await _step_body(
            llm,
            tools,
            openai_tools,
            messages,
            seq,
            cancel,
            notes,
            turn=turn,
            tool_choice=tool_choice,
            max_report_chars=max_report_chars,
            prepare=prepare,
            tracer=tracer,
        )


async def _step_body(
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
    prepare: Callable[
        [list[dict[str, Any]]], list[dict[str, Any]] | Awaitable[list[dict[str, Any]]]
    ],
    tracer: Any,
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
        tracer=tracer,
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
        cancelled = await _run_tools(tools, result, messages, seq, cancel, notes, tracer)
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
    prepare: Callable[
        [list[dict[str, Any]]], list[dict[str, Any]] | Awaitable[list[dict[str, Any]]]
    ],
    on_delta: Any = None,
    on_reasoning: Any = None,
    tracer: Any | None = None,
) -> TurnResult | None:
    await seq.emit("run.progress", {"turn": turn, "note": "thinking"})
    window = prepare(messages)
    if inspect.isawaitable(window):
        window = await window

    async def emit_reasoning(piece: str) -> None:
        await seq.emit("reasoning_delta", {"delta": piece})

    trace = tracer or NullTracer()
    model = getattr(llm, "model", None) or ""
    with trace.span("llm") as span:
        result = await llm.complete(
            window,
            openai_tools,
            tool_choice=tool_choice,
            cancel=cancel,
            on_delta=on_delta,
            on_reasoning=on_reasoning or emit_reasoning,
        )
        usage = usage_dict(result)
        if usage is not None:
            trace.add_usage(usage["prompt_tokens"], usage["completion_tokens"])
        span.annotate(
            model=model,
            finish_reason=result.finish_reason,
            message_count=len(window),
            output_chars=len(result.content or ""),
            tool_names=[call.name for call in result.tool_calls],
            usage=usage,
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
    tracer: Any,
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
    rows = await asyncio.gather(*[_invoke(tools, call, seq, cancel, tracer) for call in result.tool_calls])
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
    tracer: Any,
) -> tuple[ToolCall, bool, str]:
    args = _parse_args(call.arguments)
    started = time.perf_counter()
    with tracer.span(f"tool.{call.name}") as span:
        row, attempted = await _invoke_call(tools, call, args, seq, cancel)
        if call.name == "web_search" and attempted:
            tracer.add_search()
        span.annotate(
            ok=row[1],
            result_chars=len(row[2]),
            overflowed=result_overflowed(row[2]),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            input=tool_input(call.name, args),
        )
        return row


async def _invoke_call(
    tools: ToolBox,
    call: ToolCall,
    args: dict[str, Any],
    seq: EventEmitter,
    cancel: asyncio.Event,
) -> tuple[tuple[ToolCall, bool, str], bool]:
    await seq.emit(
        "tool_call.started",
        {"tool_call_id": call.id, "name": call.name, "args": args},
    )
    if cancel.is_set():
        await seq.emit("tool_call.finished", {"tool_call_id": call.id, "ok": False, "summary": "cancelled"})
        return (call, False, "cancelled"), False

    fn = tools.get(call.name)
    if fn is None:
        err = f"unknown tool: {call.name}"
        await seq.emit("tool_call.finished", {"tool_call_id": call.id, "ok": False, "summary": err})
        return (call, False, err), False

    try:
        text = await fn(args)
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
        await seq.emit("tool_call.finished", {"tool_call_id": call.id, "ok": False, "summary": err})
        return (call, False, err), True

    after = getattr(tools, "after_result", None)
    if after is not None:
        try:
            text = await after(call, text)
        except Exception:
            log.exception("tool overflow failed")

    if cancel.is_set():
        await seq.emit("tool_call.finished", {"tool_call_id": call.id, "ok": False, "summary": "cancelled"})
        return (call, False, "cancelled"), True

    await seq.emit("tool_call.finished", {"tool_call_id": call.id, "ok": True, "summary": text[:180]})
    return (call, True, text), True


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
