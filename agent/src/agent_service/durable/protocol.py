from __future__ import annotations

from typing import Protocol

from agent_service.workspace.paths import safe_conversation_id


class DurableStore(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...

    async def get(self, key: str) -> bytes | None: ...

    async def list(self, prefix: str) -> list[str]: ...

    async def delete_prefix(self, prefix: str) -> None: ...


def session_prefix(tenant_id: str, conversation_id: str) -> str:
    tenant = safe_conversation_id(tenant_id or "default")
    conv = safe_conversation_id(conversation_id)
    return f"tenants/{tenant}/conversations/{conv}/"
