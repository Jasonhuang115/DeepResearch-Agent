from __future__ import annotations

from typing import Any


class MemorySandboxIdStore:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def get(self, conversation_id: str) -> str | None:
        return self._data.get(conversation_id)

    async def set(self, conversation_id: str, sandbox_id: str, ttl_sec: int = 0) -> None:
        self._data[conversation_id] = sandbox_id

    async def delete(self, conversation_id: str) -> None:
        self._data.pop(conversation_id, None)


class RedisSandboxIdStore:
    def __init__(self, client: Any, *, prefix: str = "sandbox:") -> None:
        self._client = client
        self._prefix = prefix

    def _key(self, conversation_id: str) -> str:
        return f"{self._prefix}{conversation_id}"

    async def get(self, conversation_id: str) -> str | None:
        val = await self._client.get(self._key(conversation_id))
        if val is None:
            return None
        return val.decode() if isinstance(val, bytes) else str(val)

    async def set(self, conversation_id: str, sandbox_id: str, ttl_sec: int = 3300) -> None:
        kwargs: dict[str, Any] = {}
        if ttl_sec:
            kwargs["ex"] = ttl_sec
        await self._client.set(self._key(conversation_id), sandbox_id, **kwargs)

    async def delete(self, conversation_id: str) -> None:
        await self._client.delete(self._key(conversation_id))


def memory_store() -> MemorySandboxIdStore:
    return MemorySandboxIdStore()
