from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def envelope(
    *,
    run_id: str,
    conversation_id: str,
    tenant_id: str,
    seq: int,
    typ: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "v": 1,
        "run_id": run_id,
        "conversation_id": conversation_id,
        "tenant_id": tenant_id,
        "seq": seq,
        "type": typ,
        "payload": payload or {},
        "ts": datetime.now(timezone.utc).isoformat(),
    }
