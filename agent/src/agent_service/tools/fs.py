from __future__ import annotations

from typing import Any

NOT_IMPLEMENTED = "Read is not implemented yet"
WRITE_NOT_IMPLEMENTED = "Write is not implemented yet"

DESCRIPTION = "Read a text file from the workspace."

PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "File path in the workspace"},
        "offset": {"type": "integer", "minimum": 0, "description": "Line offset (0-based)"},
        "limit": {"type": "integer", "minimum": 0, "description": "Max lines to return"},
    },
    "required": ["path"],
}

WRITE_DESCRIPTION = "Create or overwrite a file in the workspace."
WRITE_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "File path in the workspace"},
        "content": {"type": "string", "description": "Full file contents"},
    },
    "required": ["path", "content"],
}


async def read_file(args: dict[str, Any]) -> str:
    path = str(args.get("path") or "").strip()
    if not path:
        return "error: path is required"
    return NOT_IMPLEMENTED


async def write_file(args: dict[str, Any]) -> str:
    path = str(args.get("path") or "").strip()
    if not path:
        return "error: path is required"
    if "content" not in args:
        return "error: content is required"
    return WRITE_NOT_IMPLEMENTED
