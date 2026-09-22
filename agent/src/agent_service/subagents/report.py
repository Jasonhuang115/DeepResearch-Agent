from __future__ import annotations

import json
import logging
from typing import Any

from agent_service.workspace.protocol import Workspace

log = logging.getLogger("agent_service.subagents")


def spec_path(sub_id: str) -> str:
    return f"subagents/{sub_id}/spec.md"


def report_path(sub_id: str) -> str:
    return f"subagents/{sub_id}/report.md"


def status_path(sub_id: str) -> str:
    return f"subagents/{sub_id}/status.json"


async def write_status(workspace: Workspace, sub_id: str, status: str, *, depth: int) -> None:
    body = {
        "id": sub_id,
        "status": status,
        "depth": depth,
        "report": report_path(sub_id),
    }
    await workspace.write_text(status_path(sub_id), json.dumps(body, ensure_ascii=False, indent=2) + "\n")


class ReportSink:
    """Captures conclusion text and terminal status. Does not forward chat events."""

    def __init__(self, workspace: Workspace, sub_id: str) -> None:
        self.workspace = workspace
        self.path = report_path(sub_id)
        self.parts: list[str] = []
        self.status = "failed"
        self.error: str | None = None

    async def emit(self, typ: str, payload: dict | None = None) -> None:
        data: dict[str, Any] = payload or {}
        if typ == "text_delta":
            piece = str(data.get("delta") or "")
            if not piece:
                return
            self.parts.append(piece)
            try:
                await self.workspace.write_text(self.path, "".join(self.parts))
            except Exception:
                log.exception("subagent report write failed")
            return
        if typ == "run.finished":
            self.status = str(data.get("status") or "failed")
            err = data.get("error")
            self.error = str(err) if err else None
