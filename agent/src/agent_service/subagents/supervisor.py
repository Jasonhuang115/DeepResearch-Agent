from __future__ import annotations

import asyncio
import logging
import math
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from agent_service.config import settings
from agent_service.observability.tracing import build_tracer
from agent_service.sources.ledger import SourceLedger
from agent_service.subagents.report import ReportSink, report_path, spec_path, write_status
from agent_service.tools import default_registry
from agent_service.tools.overflow import Overflow
from agent_service.tools.registry import ToolRegistry
from agent_service.workspace.protocol import Workspace
from research_engine.loop import run_loop
from research_engine.types import LLMClient

log = logging.getLogger("agent_service.subagents")

# Sized for one parent, ten children, and ten grandchildren in flight together.
MAX_INFLIGHT = 21
MAX_DEPTH = 2
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

SPAWN_DESCRIPTION = (
    "Start a subagent in the background and return immediately. "
    "Pass description (the task), max_time (fallback seconds for this subagent only; "
    "it stops when the task is done, and max_time only cancels a runaway), and id "
    "(a unique name you choose). The subagent writes conclusions to "
    "subagents/{id}/report.md. You are not shown that report in this turn. "
    "Do not wait for it. Depth stops at a grandchild: a grandchild cannot spawn."
)
SPAWN_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "description": {"type": "string", "description": "Task for the subagent"},
        "max_time": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": "Fallback time limit in seconds, chosen for this dispatch",
        },
        "id": {
            "type": "string",
            "description": "Unique id for this subagent. Letters, digits, underscore, hyphen.",
        },
    },
    "required": ["description", "max_time", "id"],
}

PublishWake = Callable[[dict[str, Any]], Awaitable[None]]
LLMFactory = Callable[[], LLMClient]
RegistryFactory = Callable[["Job", Workspace, "Session | None"], ToolRegistry]
EventFactory = Callable[[str, str, str], Any]


def subagent_system(description: str, *, depth: int, can_spawn: bool) -> str:
    spawn = (
        "You may call spawn_subagent to start one level of grandchildren. "
        "That call returns immediately. You will not receive their reports in this loop."
        if can_spawn
        else "You cannot spawn further subagents."
    )
    return (
        "You are a research subagent. Work only on the task below. "
        "Reply with conclusions as you learn them; those replies are saved to your report. "
        "Do not put reasoning traces or tool output in your replies. "
        "There is no turn limit. Stop when the task is done.\n\n"
        f"{spawn}\n\n"
        f"Depth: {depth}\n\n"
        f"Task:\n{description.strip()}"
    )


@dataclass
class Session:
    conversation_id: str
    tenant_id: str = ""
    user_id: str = ""
    parent_run_id: str = ""
    workspace: Workspace | None = None
    ledger: SourceLedger | None = None
    searcher: Any = None
    fetcher: Any = None
    store: Any = None


@dataclass
class Job:
    conversation_id: str
    sub_id: str
    depth: int
    description: str
    max_time: float
    run_id: str = ""
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    suppress_wake: bool = False
    timed_out: bool = False
    task: asyncio.Task[None] | None = None


class Supervisor:
    def __init__(
        self,
        *,
        publish_wake: PublishWake | None = None,
        llm_factory: LLMFactory | None = None,
        registry_factory: RegistryFactory | None = None,
    ) -> None:
        self._publish = publish_wake
        self._llm_factory = llm_factory
        self._registry_factory = registry_factory
        self._event_factory: EventFactory | None = None
        self._lock = asyncio.Lock()
        self._sessions: dict[str, Session] = {}
        self._running: dict[str, dict[str, Job]] = {}
        self._used: dict[str, set[str]] = {}
        self._keep_stops: dict[str, asyncio.Event] = {}

    def bind_publisher(self, publish_wake: PublishWake) -> None:
        self._publish = publish_wake

    def bind_events(self, factory: EventFactory) -> None:
        self._event_factory = factory

    def note_session(
        self,
        *,
        conversation_id: str,
        tenant_id: str = "",
        user_id: str = "",
        parent_run_id: str = "",
        workspace: Workspace | None = None,
        ledger: SourceLedger | None = None,
        searcher: Any = None,
        fetcher: Any = None,
        store: Any = None,
    ) -> None:
        current = self._sessions.get(conversation_id)
        if current is None:
            current = Session(conversation_id=conversation_id)
            self._sessions[conversation_id] = current
        if tenant_id:
            current.tenant_id = tenant_id
        if user_id:
            current.user_id = user_id
        if parent_run_id:
            current.parent_run_id = parent_run_id
        if workspace is not None:
            current.workspace = workspace
        if ledger is not None:
            current.ledger = ledger
        current.searcher = searcher
        current.fetcher = fetcher
        current.store = store

    def spawn_tool(
        self,
        conversation_id: str,
        parent_depth: int,
        *,
        parent_emitter: Any = None,
        parent_subagent_id: str | None = None,
    ) -> Callable[[dict[str, Any]], Awaitable[str]]:
        async def spawn(args: dict[str, Any]) -> str:
            return await self.spawn(
                conversation_id,
                parent_depth,
                args,
                parent_emitter=parent_emitter,
                parent_subagent_id=parent_subagent_id,
            )

        return spawn

    async def spawn(
        self,
        conversation_id: str,
        parent_depth: int,
        args: dict[str, Any],
        *,
        parent_emitter: Any = None,
        parent_subagent_id: str | None = None,
    ) -> str:
        if parent_depth >= MAX_DEPTH:
            return "error: spawn depth exceeded"
        description = str(args.get("description") or "").strip()
        if not description:
            return "error: description is required"
        max_time = _max_time(args.get("max_time"))
        if max_time is None:
            return "error: max_time must be a positive number of seconds"
        sub_id = str(args.get("id") or "").strip()
        if not ID_RE.fullmatch(sub_id):
            return "error: id must match [A-Za-z0-9][A-Za-z0-9_-]{0,63}"

        session = self._sessions.get(conversation_id)
        workspace = session.workspace if session is not None else None
        if workspace is None:
            return "error: workspace is not available"

        async with self._lock:
            used = self._used.setdefault(conversation_id, set())
            running = self._running.setdefault(conversation_id, {})
            if sub_id in used or sub_id in running:
                return "error: id already exists"
            if len(running) >= MAX_INFLIGHT:
                return f"error: too many subagents in flight ({MAX_INFLIGHT})"
            try:
                await workspace.read_text(spec_path(sub_id))
            except FileNotFoundError:
                pass
            else:
                used.add(sub_id)
                return "error: id already exists"
            job = Job(
                conversation_id=conversation_id,
                sub_id=sub_id,
                depth=parent_depth + 1,
                description=description,
                max_time=max_time,
            )
            used.add(sub_id)
            running[sub_id] = job
            self._ensure_keepalive(conversation_id)

        try:
            await workspace.write_text(spec_path(sub_id), description)
            await workspace.write_text(report_path(sub_id), "")
            await write_status(workspace, sub_id, "running", depth=job.depth)
        except Exception as exc:  # noqa: BLE001
            await self._release(job)
            return f"error: {exc}"

        if parent_emitter is not None:
            job.run_id = new_run_public_id()
            payload: dict[str, Any] = {
                "subagent_id": sub_id,
                "child_run_id": job.run_id,
                "description": description[:512],
                "depth": job.depth,
            }
            if parent_subagent_id:
                payload["parent_subagent_id"] = parent_subagent_id
            try:
                await parent_emitter.emit("subagent.started", payload)
            except Exception as exc:  # noqa: BLE001
                await self._release(job)
                return f"error: {exc}"

        job.task = asyncio.create_task(self._drive(job), name=f"subagent-{sub_id}")
        return f"spawned id={sub_id} status=running report={report_path(sub_id)}"

    async def cancel_conversation(self, conversation_id: str) -> None:
        async with self._lock:
            jobs = list(self._running.get(conversation_id, {}).values())
        for job in jobs:
            job.suppress_wake = True
            job.cancel.set()

    async def settle(self) -> None:
        while True:
            async with self._lock:
                tasks = [
                    job.task
                    for jobs in self._running.values()
                    for job in jobs.values()
                    if job.task is not None
                ]
            if not tasks:
                return
            await asyncio.wait(tasks)

    def _ensure_keepalive(self, conversation_id: str) -> None:
        stop = self._keep_stops.get(conversation_id)
        if stop is not None and not stop.is_set():
            return
        stop = asyncio.Event()
        self._keep_stops[conversation_id] = stop
        asyncio.create_task(
            self._keepalive(conversation_id, stop),
            name=f"subagent-keepalive-{conversation_id}",
        )

    async def _keepalive(self, conversation_id: str, stop: asyncio.Event) -> None:
        interval = settings.keepalive_sec
        if interval <= 0:
            return
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            session = self._sessions.get(conversation_id)
            if session is None or session.workspace is None:
                continue
            try:
                await session.workspace.keepalive()
                sandbox_id = _sandbox_id(session.workspace)
                if session.store is not None and sandbox_id:
                    await session.store.set(conversation_id, sandbox_id, settings.sandbox_redis_ttl_sec)
            except Exception:
                log.warning("subagent keepalive failed", exc_info=True)

    async def _drive(self, job: Job) -> None:
        tracer = build_tracer()
        session = self._sessions.get(job.conversation_id)
        started = time.perf_counter()
        status = "failed"
        with tracer.trace(
            f"subagent.{job.sub_id}",
            thread_id=job.conversation_id,
            metadata={
                "subagent_id": job.sub_id,
                "parent_run_id": session.parent_run_id if session is not None else "",
                "conversation_id": job.conversation_id,
                "depth": job.depth,
                "run_id": job.run_id,
            },
        ) as span:
            try:
                sink = ReportSink(self._workspace(job), job.sub_id)
                await self._run_bounded(job, sink, tracer)
                status = _terminal_status(job, sink.status)
            except asyncio.CancelledError:
                job.suppress_wake = True
                job.cancel.set()
                status = "cancelled"
            except Exception:
                log.exception("subagent %s failed", job.sub_id)
                status = _terminal_status(job, "failed")
            finally:
                span.annotate(
                    status=status,
                    depth=job.depth,
                    turns=tracer.current_turns(),
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                )
        await self._finish(job, status)

    async def _run_bounded(self, job: Job, sink: ReportSink, tracer: Any) -> None:
        work = asyncio.create_task(self._loop(job, sink, tracer), name=f"subagent-loop-{job.sub_id}")
        try:
            await asyncio.wait_for(asyncio.shield(work), timeout=job.max_time)
        except TimeoutError:
            job.timed_out = True
            job.cancel.set()
            try:
                await asyncio.wait_for(work, timeout=30)
            except TimeoutError:
                work.cancel()
                try:
                    await work
                except (asyncio.CancelledError, Exception):
                    pass
        except asyncio.CancelledError:
            job.suppress_wake = True
            job.cancel.set()
            work.cancel()
            try:
                await work
            except (asyncio.CancelledError, Exception):
                pass
            raise

    async def _loop(self, job: Job, sink: ReportSink, tracer: Any) -> None:
        session = self._sessions.get(job.conversation_id)
        workspace = session.workspace if session is not None else None
        if workspace is None:
            await sink.emit("run.finished", {"status": "failed", "error": "workspace is not available"})
            return
        llm = self._llm()
        child_seq = self._child_emitter(job)
        tools = self._registry(job, workspace, session, child_seq)
        messages = [
            {
                "role": "system",
                "content": subagent_system(
                    job.description,
                    depth=job.depth,
                    can_spawn=job.depth < MAX_DEPTH,
                ),
            },
            {"role": "user", "content": job.description},
        ]
        target = sink
        if child_seq is not None:
            await child_seq.emit("run.started", {})
            target = _Tee(sink, child_seq)
        await run_loop(
            llm=llm,
            tools=tools,
            messages=messages,
            seq=target,
            cancel=job.cancel,
            max_turns=None,
            max_report_chars=settings.max_report_chars,
            tracer=tracer,
        )

    def _registry(
        self,
        job: Job,
        workspace: Workspace,
        session: Session | None,
        child_seq: Any = None,
    ) -> ToolRegistry:
        if self._registry_factory is not None:
            return self._registry_factory(job, workspace, session)
        ledger = session.ledger if session and session.ledger is not None else SourceLedger(workspace)
        overflow = Overflow(
            workspace,
            run_id=job.sub_id,
            max_chars=settings.tool_result_max_chars,
            always_store=True,
        )
        registry = default_registry(
            workspace,
            ledger=ledger,
            searcher=session.searcher if session else None,
            fetcher=session.fetcher if session else None,
            overflow=overflow,
        )
        if job.depth < MAX_DEPTH:
            registry.register(
                "spawn_subagent",
                self.spawn_tool(
                    job.conversation_id,
                    job.depth,
                    parent_emitter=child_seq,
                    parent_subagent_id=job.sub_id,
                ),
                description=SPAWN_DESCRIPTION,
                parameters=SPAWN_PARAMETERS,
            )
        return registry

    def _llm(self) -> LLMClient:
        if self._llm_factory is None:
            raise RuntimeError("subagent llm factory is not configured")
        return self._llm_factory()

    def _child_emitter(self, job: Job) -> Any:
        if not job.run_id or self._event_factory is None:
            return None
        session = self._sessions.get(job.conversation_id)
        tenant_id = session.tenant_id if session is not None else ""
        return self._event_factory(job.run_id, job.conversation_id, tenant_id)

    def _workspace(self, job: Job) -> Workspace:
        session = self._sessions.get(job.conversation_id)
        if session is None or session.workspace is None:
            raise RuntimeError("workspace is not available")
        return session.workspace

    async def _finish(self, job: Job, status: str) -> None:
        session = self._sessions.get(job.conversation_id)
        workspace = session.workspace if session is not None else None
        if workspace is not None:
            try:
                await write_status(workspace, job.sub_id, status, depth=job.depth)
            except Exception:
                log.exception("subagent status write failed")
        await self._release(job)
        if job.suppress_wake or session is None:
            return
        payload = {
            "v": 1,
            "conversation_id": job.conversation_id,
            "tenant_id": session.tenant_id,
            "user_id": session.user_id,
            "id": job.sub_id,
            "status": status,
            "report_path": report_path(job.sub_id),
        }
        if self._publish is None:
            log.error("subagent wake dropped; publisher is not bound")
            return
        try:
            await self._publish(payload)
        except Exception:
            log.exception("subagent wake publish failed")

    async def _release(self, job: Job) -> None:
        stop: asyncio.Event | None = None
        async with self._lock:
            running = self._running.get(job.conversation_id)
            if running is not None:
                running.pop(job.sub_id, None)
                if not running:
                    stop = self._keep_stops.get(job.conversation_id)
        if stop is not None:
            stop.set()


def _terminal_status(job: Job, loop_status: str) -> str:
    if job.suppress_wake:
        return "cancelled"
    if job.timed_out:
        return "timed_out"
    if loop_status in {"succeeded", "failed", "cancelled"}:
        return loop_status
    return "failed"


def _max_time(raw: Any) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def _sandbox_id(workspace: Workspace) -> str | None:
    inner = getattr(workspace, "inner", workspace)
    client = getattr(inner, "client", None)
    sid = getattr(client, "sandbox_id", None)
    return str(sid) if sid else None


def new_run_public_id() -> str:
    return "run_" + uuid.uuid4().hex


class _Tee:
    def __init__(self, *sinks: Any) -> None:
        self._sinks = sinks

    async def emit(self, typ: str, payload: dict | None = None) -> None:
        for sink in self._sinks:
            await sink.emit(typ, payload)
