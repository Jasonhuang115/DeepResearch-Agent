from __future__ import annotations

from typing import Any

from agent_service.workspace.paths import format_run
from agent_service.workspace.protocol import Workspace, WorkspaceError

BASH_DESCRIPTION = "Run a shell command in the workspace."
BASH_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "Shell command"},
        "timeout_sec": {"type": "integer", "minimum": 1, "description": "Timeout in seconds"},
    },
    "required": ["command"],
}


async def bash(workspace: Workspace, args: dict[str, Any]) -> str:
    command = str(args.get("command") or "").strip()
    if not command:
        return "error: command is required"
    timeout = args.get("timeout_sec")
    try:
        result = await workspace.run(command, timeout_sec=int(timeout) if timeout else 30)
    except WorkspaceError as exc:
        return f"error: {exc}"
    return format_run(result)
