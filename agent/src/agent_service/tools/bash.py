from __future__ import annotations

from typing import Any

BASH_NOT_IMPLEMENTED = "Bash is not implemented yet"

BASH_DESCRIPTION = "Run a shell command in the workspace."
BASH_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "Shell command"},
        "timeout_sec": {"type": "integer", "minimum": 1, "description": "Timeout in seconds"},
    },
    "required": ["command"],
}


async def bash(args: dict[str, Any]) -> str:
    command = str(args.get("command") or "").strip()
    if not command:
        return "error: command is required"
    return BASH_NOT_IMPLEMENTED
