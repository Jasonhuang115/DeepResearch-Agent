from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_service.runtime.agent_runner import build_subagent_llm, run_research
from agent_service.subagents.supervisor import Supervisor
from agent_service.workspace.e2b import E2BProvider, try_sdk_factory
from agent_service.workspace.local import LocalProvider
from app.infra.config import settings
from app.infra.objects import ObjectStore, run_key
from app.infra.redis import RedisStore
from app.services.events import EventWriter
from research_engine.trace import NullTracer

log = logging.getLogger(__name__)


class BoundSandboxStore:
    def __init__(self, redis: RedisStore, user_id: str, conversation_id: str) -> None:
        self.redis = redis
        self.user_id = user_id
        self.conversation_id = conversation_id

    async def get(self, conversation_id: str) -> str | None:
        _ = conversation_id
        return await self.redis.sandbox_get(self.user_id, self.conversation_id)

    async def set(self, conversation_id: str, sandbox_id: str, ttl_sec: int = 0) -> None:
        _ = (conversation_id, ttl_sec)
        await self.redis.sandbox_set(self.user_id, self.conversation_id, sandbox_id)

    async def delete(self, conversation_id: str) -> None:
        _ = conversation_id
        await self.redis.sandbox_delete(self.user_id, self.conversation_id)


class ManagedWorkspaceProvider:
    def __init__(
        self,
        delegate: Any,
        objects: ObjectStore,
        user_id: str,
        conversation_id: str,
        run_id: str,
        restore: bool,
    ) -> None:
        self.delegate = delegate
        self.store = getattr(delegate, "store", None)
        self.objects = objects
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.run_id = run_id
        self.restore = restore
        self.workspace: Any = None
        self._checkpoint_lock = asyncio.Lock()

    async def ensure(self, conversation_id: str) -> Any:
        self.workspace = await self.delegate.ensure(conversation_id)
        if self.restore:
            await self.restore_checkpoint()
        return self.workspace

    async def restore_checkpoint(self) -> None:
        key = run_key(
            self.user_id, self.conversation_id, self.run_id, "checkpoint.json"
        )
        if not await self.objects.exists(key):
            return
        raw = json.loads((await self.objects.get(key)).decode("utf-8"))
        for path, content in dict(raw.get("files") or {}).items():
            await self.workspace.write_text(path, str(content))

    async def checkpoint(self) -> None:
        if self.workspace is None or self._checkpoint_lock.locked():
            return
        async with self._checkpoint_lock:
            files: dict[str, str] = {}
            try:
                names = await self.workspace.list_files("**/*")
            except Exception:
                log.warning("workspace listing failed during checkpoint", exc_info=True)
                return
            total = 0
            for name in names:
                if not _checkpoint_path(name):
                    continue
                try:
                    content = await self.workspace.read_text(name)
                except Exception:
                    continue
                encoded = content.encode("utf-8")
                if len(encoded) > 1_000_000 or total + len(encoded) > 5_000_000:
                    continue
                total += len(encoded)
                files[name] = content
                await self.objects.put(
                    run_key(self.user_id, self.conversation_id, self.run_id, name), encoded
                )
            payload = json.dumps({"files": files}, ensure_ascii=False).encode("utf-8")
            await self.objects.put(
                run_key(
                    self.user_id,
                    self.conversation_id,
                    self.run_id,
                    "checkpoint.json",
                ),
                payload,
            )


def _checkpoint_path(path: str) -> bool:
    return (
        path == "report.md"
        or path.startswith("sources/")
        or path.startswith("notes/")
        or path.startswith("tool-output/")
        or path.startswith("subagents/")
    )


class NormalizedEmitter:
    def __init__(self, writer: EventWriter, checkpoint: Any) -> None:
        self.writer = writer
        self.checkpoint = checkpoint
        self.final_content = ""
        self.final_status = "failed"
        self.final_error = ""
        self._text = ""
        self._text_lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None

    async def emit(self, typ: str, payload: dict | None = None) -> None:
        data = payload or {}
        if typ == "reasoning_delta":
            return
        if typ == "text_delta":
            await self._buffer_text(str(data.get("delta") or ""))
            return
        if typ == "message.completed":
            await self.flush()
            self.final_content = str(data.get("content") or "")
            return
        if typ == "run.finished":
            await self.flush()
            self.final_status = str(data.get("status") or "failed")
            self.final_error = str(data.get("error") or "")
            return

        await self.flush()
        mapped_type, mapped_payload = _normalize_event(typ, data)
        if mapped_type:
            await self.writer.emit(mapped_type, mapped_payload)
        if mapped_type in {"tool.finished", "source.added", "subtask.finished"}:
            await self.checkpoint()
            await self.writer.emit("checkpoint.saved", {})

    async def _buffer_text(self, piece: str) -> None:
        if not piece:
            return
        async with self._text_lock:
            self._text += piece
            if len(self._text.encode("utf-8")) >= 2048:
                text = self._text
                self._text = ""
            else:
                text = ""
                if self._flush_task is None or self._flush_task.done():
                    self._flush_task = asyncio.create_task(self._delayed_flush())
        if text:
            await self.writer.emit("text.delta", {"text": text})

    async def _delayed_flush(self) -> None:
        await asyncio.sleep(0.25)
        await self.flush()

    async def flush(self) -> None:
        current = asyncio.current_task()
        task = self._flush_task
        if task is not None and task is not current and not task.done():
            task.cancel()
        async with self._text_lock:
            text = self._text
            self._text = ""
        if text:
            await self.writer.emit("text.delta", {"text": text})


def _normalize_event(typ: str, payload: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    if typ == "tool_call.started":
        return "tool.started", payload
    if typ == "tool_call.finished":
        return "tool.finished", payload
    if typ == "subagent.started":
        payload.pop("child_run_id", None)
        return "subtask.started", payload
    if typ == "subagent.finished":
        return "subtask.finished", payload
    if typ in {
        "run.started",
        "run.progress",
        "source.added",
        "checkpoint.saved",
        "error",
    }:
        return typ, payload
    return None, payload


@dataclass(frozen=True)
class ResearchResult:
    status: str
    content: str
    error: str


async def execute_research(
    *,
    command: dict[str, Any],
    writer: EventWriter,
    cancel: asyncio.Event,
    redis: RedisStore,
    objects: ObjectStore,
    user_id: str,
    attempt_count: int,
) -> ResearchResult:
    conversation_id = str(command["conversation_id"])
    run_id = str(command["run_id"])
    provider = _provider(redis, objects, user_id, conversation_id, run_id, attempt_count > 1)
    emitter = NormalizedEmitter(writer, provider.checkpoint)
    supervisor = Supervisor(llm_factory=build_subagent_llm)
    await run_research(
        command,
        emitter,
        cancel,
        workspace_provider=provider,
        supervisor=supervisor,
        tracer=NullTracer(),
    )
    await emitter.flush()
    await supervisor.settle()
    await provider.checkpoint()
    if emitter.final_content:
        await objects.put(
            run_key(user_id, conversation_id, run_id, "report.md"),
            emitter.final_content.encode("utf-8"),
        )
    return ResearchResult(emitter.final_status, emitter.final_content, emitter.final_error)


def _provider(
    redis: RedisStore,
    objects: ObjectStore,
    user_id: str,
    conversation_id: str,
    run_id: str,
    restore: bool,
) -> ManagedWorkspaceProvider:
    if settings.sandbox_mode == "e2b":
        if not settings.e2b_api_key:
            raise RuntimeError("E2B_API_KEY is required when SANDBOX_MODE=e2b")
        factory = try_sdk_factory(settings.e2b_api_key)
        if factory is None:
            raise RuntimeError("E2B SDK is unavailable")
        delegate: Any = E2BProvider(
            factory=factory,
            store=BoundSandboxStore(redis, user_id, conversation_id),
            ttl_sec=settings.sandbox_ttl_seconds,
        )
    elif settings.sandbox_mode == "local":
        delegate = LocalProvider(Path("../data/workspaces"))
    else:
        raise RuntimeError(f"unsupported SANDBOX_MODE={settings.sandbox_mode}")
    return ManagedWorkspaceProvider(
        delegate, objects, user_id, conversation_id, run_id, restore
    )
