from __future__ import annotations

from typing import Any

from agent_service.config import settings
from agent_service.context import pack_messages, prepare_messages
from agent_service.runtime.system_prompt import build_system_prompt, detect_reply_language
from agent_service.sources.ingest import ingest_attachments
from agent_service.sources.ledger import SourceLedger
from agent_service.tools import ToolRegistry, default_registry
from agent_service.tools.web_search import Searcher
from agent_service.workspace import WorkspaceProvider, default_provider
from research_engine.llm.openai_compat import OpenAICompatLLM
from research_engine.loop import run_loop
from research_engine.types import EventEmitter, LLMClient

MISSING_KEY = "OPENAI_API_KEY is not set"


def _llm_extra_body() -> dict[str, Any] | None:
    extra: dict[str, Any] = {}
    thinking = settings.openai_thinking.strip().lower()
    if thinking in {"1", "true", "on", "enabled"}:
        extra["thinking"] = {"type": "enabled"}
    elif thinking in {"0", "false", "off", "disabled"}:
        extra["thinking"] = {"type": "disabled"}
    effort = settings.openai_reasoning_effort.strip()
    if effort:
        extra["reasoning_effort"] = effort
    return extra or None


async def run_research(
    cmd: dict,
    seq: EventEmitter,
    cancel: Any,
    *,
    llm: LLMClient | None = None,
    tools: ToolRegistry | None = None,
    max_turns: int | None = None,
    workspace_provider: WorkspaceProvider | None = None,
    searcher: Searcher | None = None,
    fetcher: Any | None = None,
) -> None:
    limit = settings.max_turns if max_turns is None else max_turns
    question = ((cmd.get("request") or {}).get("content") or "").strip()
    system = build_system_prompt(
        conversation_id=str(cmd.get("conversation_id") or ""),
        run_id=str(cmd.get("run_id") or ""),
        reply_language=detect_reply_language(question),
        extra={"web_search_provider": settings.web_search_provider},
    )

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
            extra_body=_llm_extra_body(),
        )

    registry = tools
    workspace = None
    ledger = None
    if registry is None:
        provider = workspace_provider or default_provider()
        workspace = await provider.ensure(str(cmd.get("conversation_id") or ""))
        if workspace.notice:
            system = f"{system.rstrip()}\n\n<workspace>\n{workspace.notice}\n</workspace>\n"
        ledger = SourceLedger(workspace, seq=seq)
        registry = default_registry(workspace, ledger=ledger, searcher=searcher, fetcher=fetcher)
    elif workspace_provider is not None:
        workspace = await workspace_provider.ensure(str(cmd.get("conversation_id") or ""))
        ledger = SourceLedger(workspace, seq=seq)

    manifest = ""
    model = getattr(llm, "model", None) or settings.openai_model
    await seq.emit("run.started", {"model": model})
    if workspace is not None and ledger is not None:
        manifest = await ingest_attachments(cmd, workspace, ledger)

    messages = _chat_messages(cmd, system, manifest=manifest)
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


def _chat_messages(cmd: dict, system: str, *, manifest: str = "") -> list[dict[str, Any]]:
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
    user_body = question
    if manifest:
        user_body = f"{question}\n\n{manifest}".strip() if question else manifest
    if user_body:
        last = out[-1] if len(out) > 1 else None
        if last is not None and last.get("role") == "user" and last.get("content") == question:
            last["content"] = user_body
        elif last is None or last.get("role") != "user" or last.get("content") != user_body:
            out.append({"role": "user", "content": user_body})
    return out
