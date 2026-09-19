from __future__ import annotations

from typing import Any

from agent_service.config import settings
from agent_service.context import pack_messages, prepare_messages
from agent_service.runtime.system_prompt import build_system_prompt, detect_reply_language
from agent_service.tools import ToolRegistry, default_registry
from research_engine.llm.openai_compat import OpenAICompatLLM
from research_engine.loop import run_loop
from research_engine.types import EventEmitter, LLMClient

MISSING_KEY = "OPENAI_API_KEY is not set"


async def run_research(
    cmd: dict,
    seq: EventEmitter,
    cancel: Any,
    *,
    llm: LLMClient | None = None,
    tools: ToolRegistry | None = None,
    max_turns: int | None = None,
) -> None:
    limit = settings.max_turns if max_turns is None else max_turns
    registry = tools or default_registry()
    question = ((cmd.get("request") or {}).get("content") or "").strip()
    system = build_system_prompt(
        conversation_id=str(cmd.get("conversation_id") or ""),
        run_id=str(cmd.get("run_id") or ""),
        reply_language=detect_reply_language(question),
    )
    messages = _chat_messages(cmd, system)

    if llm is None:
        if not settings.openai_api_key:
            await seq.emit("run.started", {"model": settings.openai_model})
            await seq.emit("error", {"message": MISSING_KEY})
            await seq.emit("message.completed", {"content": "", "truncated": False})
            await seq.emit("run.finished", {"status": "failed", "error": MISSING_KEY})
            return
        llm = OpenAICompatLLM(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            base_url=settings.openai_base_url or None,
        )

    model = getattr(llm, "model", None) or settings.openai_model
    await seq.emit("run.started", {"model": model})
    await run_loop(
        llm=llm,
        tools=registry,
        messages=messages,
        seq=seq,
        cancel=cancel,
        max_turns=limit,
        max_report_chars=settings.max_report_chars,
        prepare_messages=prepare_messages,
    )


def _chat_messages(cmd: dict, system: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for item in pack_messages(cmd.get("messages") or []):
        role = item.get("role") or "user"
        if role not in ("user", "assistant", "system"):
            continue
        content = item.get("content") or ""
        if not content:
            continue
        out.append({"role": role, "content": content})
    question = ((cmd.get("request") or {}).get("content") or "").strip()
    if question:
        last = out[-1] if len(out) > 1 else None
        if last is None or last.get("role") != "user" or last.get("content") != question:
            out.append({"role": "user", "content": question})
    return out
