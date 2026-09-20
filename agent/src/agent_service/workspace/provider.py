from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agent_service.config import settings
from agent_service.workspace.e2b import E2BProvider, try_sdk_factory
from agent_service.workspace.local import LocalProvider
from agent_service.workspace.protocol import E2BFactory, SandboxIdStore, WorkspaceProvider
from agent_service.workspace.store import MemorySandboxIdStore, RedisSandboxIdStore

log = logging.getLogger("agent_service.workspace")

_provider: WorkspaceProvider | None = None


def reset_provider() -> None:
    global _provider
    _provider = None


def default_provider() -> WorkspaceProvider:
    global _provider
    if _provider is None:
        _provider = build_provider()
    return _provider


def build_provider(
    *,
    mode: str | None = None,
    factory: E2BFactory | None = None,
    store: SandboxIdStore | None = None,
    workspace_root: str | None = None,
    e2b_api_key: str | None = None,
) -> WorkspaceProvider:
    local = LocalProvider(Path(workspace_root or settings.workspace_root))
    chosen = (mode if mode is not None else settings.workspace_mode or "auto").strip().lower()
    key = settings.e2b_api_key if e2b_api_key is None else e2b_api_key
    want_e2b = chosen == "e2b" or (chosen == "auto" and bool(key))
    if not want_e2b:
        return local
    if not key and factory is None:
        log.info("E2B requested without API key; using local workspace")
        return local
    e2b_factory = factory if factory is not None else try_sdk_factory(key)
    if e2b_factory is None:
        log.warning("E2B backend unavailable; using local workspace")
        return local
    return E2BProvider(
        factory=e2b_factory,
        store=store if store is not None else _build_store(),
        local=local,
        timeout_sec=settings.e2b_timeout_sec,
        ttl_sec=settings.sandbox_redis_ttl_sec,
    )


def _build_store() -> SandboxIdStore:
    client = _try_redis()
    if client is None:
        return MemorySandboxIdStore()
    return RedisSandboxIdStore(client)


def _try_redis() -> Any | None:
    try:
        import redis.asyncio as redis
    except ImportError:
        return None
    try:
        return redis.Redis.from_url(f"redis://{settings.redis_addr}", decode_responses=True)
    except Exception:
        log.warning("Redis unavailable for sandbox id mapping; using memory store")
        return None
