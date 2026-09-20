from pathlib import Path

import pytest

from agent_service.config import settings
from agent_service.workspace.e2b import (
    E2BProvider,
    E2BWorkspace,
    FakeE2BFactory,
    LOST_NOTICE,
    FALLBACK_NOTICE,
)
from agent_service.workspace.local import LocalProvider
from agent_service.workspace.provider import build_provider
from agent_service.workspace.store import MemorySandboxIdStore, RedisSandboxIdStore
from agent_service.tools.fs import read_file, write_file


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value
        if ex:
            self.ttls[key] = ex

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


@pytest.mark.asyncio
async def test_e2b_workspace_roundtrip() -> None:
    factory = FakeE2BFactory()
    client = await factory.create(60)
    ws = E2BWorkspace(client=client)
    await write_file(ws, {"path": "notes.md", "content": "from e2b"})
    text = await read_file(ws, {"path": "notes.md"})
    assert "from e2b" in text
    assert "escapes workspace" in await read_file(ws, {"path": "../secret"})


@pytest.mark.asyncio
async def test_e2b_provider_reuses_then_rebuilds() -> None:
    factory = FakeE2BFactory()
    store = MemorySandboxIdStore()
    provider = E2BProvider(factory=factory, store=store, timeout_sec=10, ttl_sec=9)
    first = await provider.ensure("conv_a")
    assert first.notice is None
    assert await store.get("conv_a") == first.client.sandbox_id
    again = await provider.ensure("conv_a")
    assert again.client.sandbox_id == first.client.sandbox_id

    factory.fail_connect = True
    rebuilt = await provider.ensure("conv_a")
    assert rebuilt.notice == LOST_NOTICE
    assert rebuilt.client.sandbox_id != first.client.sandbox_id


@pytest.mark.asyncio
async def test_e2b_create_falls_back_to_local(tmp_path: Path) -> None:
    factory = FakeE2BFactory()
    factory.fail_create = True
    provider = E2BProvider(
        factory=factory,
        store=MemorySandboxIdStore(),
        local=LocalProvider(tmp_path),
    )
    ws = await provider.ensure("conv_b")
    assert FALLBACK_NOTICE in (ws.notice or "")
    await ws.write_text("ok.md", "local")
    assert (tmp_path / "conv_b" / "ok.md").read_text(encoding="utf-8") == "local"


@pytest.mark.asyncio
async def test_build_provider_auto_local_without_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    monkeypatch.setattr(settings, "e2b_api_key", "")
    provider = build_provider(mode="auto")
    assert isinstance(provider, LocalProvider)


@pytest.mark.asyncio
async def test_build_provider_auto_e2b_with_factory(tmp_path: Path) -> None:
    provider = build_provider(
        mode="auto",
        e2b_api_key="ek_test",
        factory=FakeE2BFactory(),
        store=MemorySandboxIdStore(),
        workspace_root=str(tmp_path),
    )
    assert isinstance(provider, E2BProvider)
    ws = await provider.ensure("c")
    assert isinstance(ws, E2BWorkspace)


@pytest.mark.asyncio
async def test_build_provider_e2b_without_key_uses_local(tmp_path: Path) -> None:
    provider = build_provider(mode="e2b", e2b_api_key="", workspace_root=str(tmp_path))
    assert isinstance(provider, LocalProvider)


@pytest.mark.asyncio
async def test_redis_sandbox_store() -> None:
    client = FakeRedis()
    store = RedisSandboxIdStore(client)
    assert await store.get("c1") is None
    await store.set("c1", "sb_9", ttl_sec=12)
    assert await store.get("c1") == "sb_9"
    assert client.ttls["sandbox:c1"] == 12
    await store.delete("c1")
    assert await store.get("c1") is None
