from __future__ import annotations

import asyncio
import logging

from agent_service.config import settings
from agent_service.context import pack_messages
from agent_service.llm.mock import MockLLM
from agent_service.producer.events import EventSeq
from agent_service.tools import default_registry

log = logging.getLogger("agent.loop")

TURNS = (
    ("Map the main electrolyte families and who is shipping them.", "solid-state battery electrolyte families 2024 2026"),
    ("Compare sulfide vs oxide vs polymer on conductivity, stability, and scale.", "sulfide oxide polymer electrolyte comparison conductivity"),
    ("Collect failure modes and commercialization risks.", "solid-state electrolyte scale-up risks dendrite moisture"),
)


async def run_research(cmd: dict, seq: EventSeq, cancel: asyncio.Event) -> None:
    messages = pack_messages(cmd.get("messages") or [])
    question = (cmd.get("request") or {}).get("content") or ""
    llm = MockLLM()
    tools = default_registry()
    await seq.emit("run.started", {"model": "mock-react-v1"})
    parts: list[str] = []

    try:
        for i, (thought, query) in enumerate(TURNS, start=1):
            if cancel.is_set():
                await _finish(seq, "cancelled", "\n\n".join(parts), "cancelled")
                return
            await seq.emit("run.progress", {"turn": i, "note": "thinking"})
            await _delta(seq, "reasoning_delta", thought + f" User asked: {question[:80]}")
            _ = await llm.complete(thought)
            tid = f"call_{i}"
            await seq.emit("tool_call.started", {"tool_call_id": tid, "name": "web_search", "args": {"query": query}})
            result = await tools.get("web_search")({"query": query})
            if cancel.is_set():
                await seq.emit("tool_call.finished", {"tool_call_id": tid, "ok": False, "summary": "cancelled"})
                await _finish(seq, "cancelled", "\n\n".join(parts), "cancelled")
                return
            await seq.emit("tool_call.finished", {"tool_call_id": tid, "ok": True, "summary": result[:180]})
            parts.append(f"### Turn {i}\n{thought}\n\n{result}")
            await asyncio.sleep(0.2)

        report = _report(question, messages, parts)
        truncated = False
        if len(report) > settings.max_report_chars:
            report = report[: settings.max_report_chars]
            truncated = True
        for chunk in _chunks(report, 24):
            if cancel.is_set():
                await _finish(seq, "cancelled", report[: max(0, report.find(chunk))], "cancelled")
                return
            await seq.emit("text_delta", {"delta": chunk})
            await asyncio.sleep(0.03)
        await seq.emit("message.completed", {"content": report, "truncated": truncated})
        await seq.emit("run.finished", {"status": "succeeded"})
    except Exception as exc:  # noqa: BLE001
        log.exception("run failed")
        text = "\n\n".join(parts)
        await seq.emit("error", {"message": str(exc)})
        await _finish(seq, "failed", text, str(exc))


async def _finish(seq: EventSeq, status: str, content: str, error: str | None) -> None:
    await seq.emit("message.completed", {"content": content, "truncated": False})
    payload: dict = {"status": status}
    if error:
        payload["error"] = error
    await seq.emit("run.finished", payload)


async def _delta(seq: EventSeq, typ: str, text: str) -> None:
    for chunk in _chunks(text, 40):
        await seq.emit(typ, {"delta": chunk})
        await asyncio.sleep(0.02)


def _chunks(text: str, n: int) -> list[str]:
    return [text[i : i + n] for i in range(0, len(text), n)] or [""]


def _report(question: str, messages: list[dict], notes: list[str]) -> str:
    prior = ""
    if len(messages) > 1:
        prior = f"This continues a thread of {len(messages)} messages.\n\n"
    return f"""# Deep research report

{prior}**Question.** {question or "(empty)"}

## Approach

This is a mock ReAct run: three think → `web_search` → observe cycles, then a long-form writeup.
Replace `llm/` and `tools/` to turn this into a real researcher. Context packing and subagents stay in this service.

## Findings

{chr(10).join(notes)}

## Comparison

| Route | Strength | Weakness | 2024–2026 read |
| --- | --- | --- | --- |
| Sulfide | High conductivity, stack-friendly | Moisture, H2S, cost | Leading in several OEM pilots |
| Oxide | Chemical stability, air handling | Grain-boundary resistance, sintering | Steady, slower cell-level wins |
| Polymer | Processable, safer handling | Low room-temp conductivity | Niche / hybrid layers |

## Risks

1. Interface contact loss after cycling.
2. Scale of precursor purity for sulfides.
3. Dendrite penetration along defects.
4. Claims outrunning measured stack pressure and temperature windows.

## Judgment

Treat sulfide as the near-term high-performance bet with a messy process tax.
Keep oxide as the conservative baseline. Polymer is a processing layer, not a standalone cathode-facing electrolyte for energy-dense EV cells.

## Open questions

- What stack pressure do the cited cells actually run?
- Are moisture specs at plant level, or only pouch-level dry rooms?
- Which failure reports are cell vs module?

---

*Generated by the mock agent. Not a substitute for primary literature.*
"""
