from __future__ import annotations

import logging
from dataclasses import dataclass

from agent_service.durable.protocol import DurableStore, session_prefix
from agent_service.workspace.protocol import RunResult, Workspace

log = logging.getLogger("agent_service.durable")


@dataclass
class SyncingWorkspace:
    """Sandbox working copy; DurableStore is the canonical prefix."""

    inner: Workspace
    store: DurableStore
    prefix: str
    notice: str | None = None

    def __post_init__(self) -> None:
        if self.notice is None:
            self.notice = getattr(self.inner, "notice", None)

    async def read_text(self, path: str) -> str:
        return await self.inner.read_text(path)

    async def write_text(self, path: str, content: str) -> None:
        await self.inner.write_text(path, content)
        await self._put(path, content.encode("utf-8"))

    async def write_bytes(self, path: str, data: bytes) -> None:
        await self.inner.write_bytes(path, data)
        await self._put(path, data)

    async def list_files(self, pattern: str = "**/*") -> list[str]:
        return await self.inner.list_files(pattern)

    async def run(self, command: str, *, timeout_sec: int = 30) -> RunResult:
        return await self.inner.run(command, timeout_sec=timeout_sec)

    async def keepalive(self) -> None:
        fn = getattr(self.inner, "keepalive", None)
        if fn is not None:
            await fn()

    async def hydrate(self) -> int:
        keys = await self.store.list(self.prefix)
        n = 0
        for key in keys:
            if not key or key.endswith("/"):
                continue
            if not key.startswith(self.prefix):
                continue
            rel = key[len(self.prefix) :].lstrip("/")
            if not rel or ".." in rel.split("/"):
                continue
            data = await self.store.get(key)
            if data is None:
                continue
            await self.inner.write_bytes(rel, data)
            n += 1
        return n

    async def _put(self, path: str, data: bytes) -> None:
        rel = (path or "").replace("\\", "/").lstrip("/")
        if not rel or ".." in rel.split("/"):
            return
        try:
            await self.store.put(self.prefix + rel, data)
        except Exception:
            log.exception("durable put failed for %s", rel)


async def bind_workspace(
    inner: Workspace,
    *,
    tenant_id: str,
    conversation_id: str,
    store: DurableStore,
    force_hydrate: bool = False,
) -> SyncingWorkspace:
    ws = SyncingWorkspace(inner=inner, store=store, prefix=session_prefix(tenant_id, conversation_id), notice=inner.notice)
    if force_hydrate or await _looks_empty(inner):
        try:
            await ws.hydrate()
        except Exception:
            log.exception("hydrate failed for %s", conversation_id)
    return ws


async def _looks_empty(workspace: Workspace) -> bool:
    for path in ("sources/index.json", "sources/ledger.json"):
        try:
            await workspace.read_text(path)
            return False
        except FileNotFoundError:
            continue
        except Exception:
            continue
    try:
        names = await workspace.list_files("**/*")
    except Exception:
        return True
    return not names
