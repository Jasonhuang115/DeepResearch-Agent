from __future__ import annotations

import asyncio
import logging
from typing import Any

from agent_service.config import settings
from agent_service.context import ContextPacker, pack_messages
from agent_service.observability.tracing import build_tracer
from agent_service.durable import bind_workspace, build_durable_store
from agent_service.runtime.system_prompt import build_system_prompt, detect_reply_language
from agent_service.sources.ingest import ingest_attachments
from agent_service.sources.ledger import SourceLedger
from agent_service.subagents.supervisor import SPAWN_DESCRIPTION, SPAWN_PARAMETERS, Supervisor
from agent_service.subagents.wake import wake_reports_block, wake_user_cue
from agent_service.tools import ToolRegistry, default_registry
from agent_service.tools.overflow import Overflow
from agent_service.tools.web_search import Searcher
from agent_service.workspace import WorkspaceProvider, default_provider
from agent_service.workspace.e2b import LOST_NOTICE
from research_engine.llm.openai_compat import OpenAICompatLLM
from research_engine.loop import run_loop
from research_engine.types import EventEmitter, LLMClient

log = logging.getLogger("agent_service.runtime")

MISSING_KEY = "OPENAI_API_KEY is not set"


def build_subagent_llm() -> OpenAICompatLLM:
    return OpenAICompatLLM(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        base_url=settings.openai_base_url or None,
        extra_body=_llm_extra_body(),
    )


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


class _StatusTap:
    def __init__(self, inner: EventEmitter) -> None:
        self._inner = inner
        self.status = ""

    async def emit(self, typ: str, payload: dict | None = None) -> None:
        if typ == "run.finished":
            self.status = str((payload or {}).get("status") or "")
        await self._inner.emit(typ, payload)


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
    durable_store: Any | None = None,
    supervisor: Supervisor | None = None,
    tracer: Any | None = None,
) -> None:
    active = tracer if tracer is not None else build_tracer()
    conversation_id = str(cmd.get("conversation_id") or "")
    tap = _StatusTap(seq)
    with active.trace(
        "run",
        thread_id=conversation_id,
        metadata={
            "run_id": str(cmd.get("run_id") or ""),
            "conversation_id": conversation_id,
            "tenant_id": str(cmd.get("tenant_id") or ""),
        },
    ) as run_span:
        try:
            await _execute(
                cmd,
                tap,
                cancel,
                llm=llm,
                tools=tools,
                max_turns=max_turns,
                workspace_provider=workspace_provider,
                searcher=searcher,
                fetcher=fetcher,
                durable_store=durable_store,
                supervisor=supervisor,
                tracer=active,
                run_span=run_span,
            )
        finally:
            run_span.annotate(status=tap.status or "failed")


async def _execute(
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
    durable_store: Any | None = None,
    supervisor: Supervisor | None = None,
    tracer: Any,
    run_span: Any | None = None,
) -> None:
    limit = settings.max_turns if max_turns is None else max_turns
    question = ((cmd.get("request") or {}).get("content") or "").strip()
    reply_language = detect_reply_language(question or _last_user_text(cmd))
    system = build_system_prompt(
        conversation_id=str(cmd.get("conversation_id") or ""),
        run_id=str(cmd.get("run_id") or ""),
        reply_language=reply_language,
        extra={"web_search_provider": settings.web_search_provider},
    )
    reports = wake_reports_block(cmd.get("wake"))
    if reports:
        system = f"{system.rstrip()}\n\n<subagent-reports>\n{reports}\n</subagent-reports>\n"

    if llm is None:
        if not settings.openai_api_key:
            if run_span is not None:
                run_span.annotate(model=settings.openai_model)
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
    sandbox_store = None
    provider = None
    if registry is None:
        provider = workspace_provider or default_provider()
        workspace = await _ensure_workspace(provider, cmd)
        sandbox_store = getattr(provider, "store", None)
        if workspace.notice:
            system = f"{system.rstrip()}\n\n<workspace>\n{workspace.notice}\n</workspace>\n"
        store = durable_store if durable_store is not None else build_durable_store()
        workspace = await bind_workspace(
            workspace,
            tenant_id=str(cmd.get("tenant_id") or ""),
            conversation_id=str(cmd.get("conversation_id") or ""),
            store=store,
            force_hydrate=_needs_hydrate(workspace.notice),
        )
        ledger = SourceLedger(workspace, seq=seq)
        overflow = Overflow(
            workspace,
            run_id=str(cmd.get("run_id") or "run"),
            max_chars=settings.tool_result_max_chars,
        )
        registry = default_registry(
            workspace,
            ledger=ledger,
            searcher=searcher,
            fetcher=fetcher,
            overflow=overflow,
        )
    elif workspace_provider is not None:
        provider = workspace_provider
        workspace = await _ensure_workspace(provider, cmd)
        sandbox_store = getattr(provider, "store", None)
        store = durable_store if durable_store is not None else build_durable_store()
        workspace = await bind_workspace(
            workspace,
            tenant_id=str(cmd.get("tenant_id") or ""),
            conversation_id=str(cmd.get("conversation_id") or ""),
            store=store,
            force_hydrate=_needs_hydrate(workspace.notice),
        )
        ledger = SourceLedger(workspace, seq=seq)
        if registry.overflow is None:
            registry.overflow = Overflow(
                workspace,
                run_id=str(cmd.get("run_id") or "run"),
                max_chars=settings.tool_result_max_chars,
            )

    if supervisor is not None and workspace is not None and registry is not None:
        supervisor.note_session(
            conversation_id=str(cmd.get("conversation_id") or ""),
            tenant_id=str(cmd.get("tenant_id") or ""),
            user_id=str(cmd.get("user_id") or ""),
            workspace=workspace,
            ledger=ledger,
            searcher=searcher,
            fetcher=fetcher,
            store=sandbox_store,
            parent_run_id=str(cmd.get("run_id") or ""),
        )
        registry.register(
            "spawn_subagent",
            supervisor.spawn_tool(
                str(cmd.get("conversation_id") or ""),
                0,
                parent_emitter=seq,
            ),
            description=SPAWN_DESCRIPTION,
            parameters=SPAWN_PARAMETERS,
        )

    manifest = ""
    model = getattr(llm, "model", None) or settings.openai_model
    if run_span is not None:
        run_span.annotate(model=model)
    await seq.emit("run.started", {"model": model})
    if workspace is not None and ledger is not None:
        manifest = await ingest_attachments(cmd, workspace, ledger)

    packer = ContextPacker(
        llm=llm,
        workspace=workspace,
        seq=seq,
        budget=settings.context_input_budget,
        tracer=tracer,
    )
    messages = _chat_messages(
        cmd,
        system,
        manifest=manifest,
        wake_cue=wake_user_cue(reply_language) if reports else "",
    )
    keep_stop = asyncio.Event()
    keep_task = _start_keepalive(
        workspace,
        store=sandbox_store,
        conversation_id=str(cmd.get("conversation_id") or ""),
        stop=keep_stop,
    )
    try:
        await run_loop(
            llm=llm,
            tools=registry,
            messages=messages,
            seq=seq,
            cancel=cancel,
            max_turns=limit,
            max_report_chars=settings.max_report_chars,
            max_output_continuations=settings.max_output_continuations,
            prepare_messages=packer,
            tracer=tracer,
        )
    finally:
        keep_stop.set()
        if keep_task is not None:
            keep_task.cancel()
            try:
                await keep_task
            except (asyncio.CancelledError, Exception):
                pass


async def _ensure_workspace(provider: WorkspaceProvider, cmd: dict) -> Any:
    cid = str(cmd.get("conversation_id") or "")
    tenant_id = str(cmd.get("tenant_id") or "")
    try:
        return await provider.ensure(cid, tenant_id=tenant_id)  # type: ignore[call-arg]
    except TypeError:
        return await provider.ensure(cid)


def _needs_hydrate(notice: str | None) -> bool:
    text = notice or ""
    return LOST_NOTICE in text


def _start_keepalive(
    workspace: Any,
    *,
    store: Any,
    conversation_id: str,
    stop: asyncio.Event,
) -> asyncio.Task[None] | None:
    if workspace is None:
        return None
    interval = settings.keepalive_sec
    if interval <= 0:
        return None
    sandbox_id = _sandbox_id(workspace)
    ttl = settings.sandbox_redis_ttl_sec

    async def _loop() -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            try:
                await workspace.keepalive()
                if store is not None and sandbox_id and conversation_id:
                    await store.set(conversation_id, sandbox_id, ttl)
            except Exception:
                log.warning("workspace keepalive failed", exc_info=True)

    return asyncio.create_task(_loop(), name=f"keepalive-{conversation_id or 'ws'}")


def _sandbox_id(workspace: Any) -> str | None:
    inner = getattr(workspace, "inner", workspace)
    client = getattr(inner, "client", None)
    sid = getattr(client, "sandbox_id", None)
    return str(sid) if sid else None


def _last_user_text(cmd: dict) -> str:
    for item in reversed(cmd.get("messages") or []):
        if (item.get("role") or "") == "user" and (item.get("content") or "").strip():
            return str(item.get("content") or "")
    return ""


def _chat_messages(
    cmd: dict,
    system: str,
    *,
    manifest: str = "",
    wake_cue: str = "",
) -> list[dict[str, Any]]:
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
    if wake_cue:
        out.append({"role": "user", "content": wake_cue})
    return out
