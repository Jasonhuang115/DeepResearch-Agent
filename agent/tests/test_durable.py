from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent_service.durable.local import LocalDiskStore
from agent_service.durable.protocol import session_prefix
from agent_service.durable.sync import bind_workspace
from agent_service.runtime.agent_runner import _start_keepalive
from agent_service.sources.ledger import SourceLedger
from agent_service.workspace.e2b import E2BProvider, E2BWorkspace, FakeE2BFactory, LOST_NOTICE
from agent_service.workspace.local import LocalProvider
from agent_service.workspace.store import RedisSandboxIdStore
from agent_service.config import settings


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.sets = 0

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.sets += 1
        self.data[key] = value
        if ex:
            self.ttls[key] = ex

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


@pytest.mark.asyncio
async def test_hydrate_is_tenant_isolated(tmp_path: Path) -> None:
    store = LocalDiskStore(tmp_path / "oss")
    prefix_a = session_prefix("ten_a", "conv_a")
    prefix_b = session_prefix("ten_b", "conv_b")
    await store.put(prefix_a + "sources/src_03.md", b"body-a")
    await store.put(prefix_b + "sources/src_03.md", b"secret-b")
    ws_a = await LocalProvider(tmp_path / "sandboxes").ensure("conv_a")
    bound = await bind_workspace(ws_a, tenant_id="ten_a", conversation_id="conv_a", store=store, force_hydrate=True)
    assert await bound.read_text("sources/src_03.md") == "body-a"
    names = await bound.list_files("**/*")
    assert "sources/src_03.md" in names
    assert all("secret-b" not in name for name in names)
    with pytest.raises(FileNotFoundError):
        await bound.read_text("sources/secret.md")
    listed = await store.list(prefix_a)
    assert listed == [prefix_a + "sources/src_03.md"]


@pytest.mark.asyncio
async def test_lost_sandbox_hydrates_src_from_same_prefix(tmp_path: Path) -> None:
    store = LocalDiskStore(tmp_path / "oss")
    factory = FakeE2BFactory()
    provider = E2BProvider(factory=factory, timeout_sec=10, ttl_sec=9)
    first = await provider.ensure("conv_z")
    bound = await bind_workspace(first, tenant_id="ten_a", conversation_id="conv_z", store=store)
    await bound.write_text("sources/src_03.md", "from-first-sandbox")
    factory.fail_connect = True
    rebuilt = await provider.ensure("conv_z")
    assert rebuilt.notice == LOST_NOTICE
    restored = await bind_workspace(
        rebuilt, tenant_id="ten_a", conversation_id="conv_z", store=store, force_hydrate=True
    )
    assert await restored.read_text("sources/src_03.md") == "from-first-sandbox"


@pytest.mark.asyncio
async def test_ledger_writes_index_catalog(tmp_path: Path) -> None:
    ws = await LocalProvider(tmp_path).ensure("c")
    store = LocalDiskStore(tmp_path / "oss")
    bound = await bind_workspace(ws, tenant_id="ten", conversation_id="c", store=store)
    ledger = SourceLedger(bound)
    await ledger.add(url="https://example.com/a", title="Example", provider="web_fetch", body="# Example\n\nHi")
    index = await bound.read_text("sources/index.json")
    assert "src_01" in index
    assert "sources/src_01.md" in index
    assert "web_fetch" in index
    raw = await store.get(session_prefix("ten", "c") + "sources/src_01.md")
    assert raw is not None and b"Hi" in raw


@pytest.mark.asyncio
async def test_keepalive_refreshes_timeout_and_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "keepalive_sec", 0.05)
    monkeypatch.setattr(settings, "sandbox_redis_ttl_sec", 12)
    factory = FakeE2BFactory()
    client = await factory.create(8)
    ws = E2BWorkspace(client=client, timeout_sec=8)
    redis = FakeRedis()
    store = RedisSandboxIdStore(redis)
    await store.set("conv_k", client.sandbox_id, ttl_sec=12)
    stop = asyncio.Event()
    task = _start_keepalive(ws, store=store, conversation_id="conv_k", stop=stop)
    assert task is not None
    await asyncio.sleep(0.16)
    stop.set()
    await asyncio.wait_for(task, timeout=1)
    assert getattr(client, "timeout_calls", 0) >= 1
    assert redis.sets >= 2
    assert redis.ttls["sandbox:conv_k"] == 12
