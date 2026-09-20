from __future__ import annotations

import re
from typing import Any

from agent_service.workspace.protocol import PathEscapeError, Workspace, WorkspaceError

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

EDIT_DESCRIPTION = "Replace text in a workspace file. old_string must match exactly."
EDIT_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "File path in the workspace"},
        "old_string": {"type": "string", "description": "Exact text to find"},
        "new_string": {"type": "string", "description": "Replacement text"},
        "replace_all": {"type": "boolean", "description": "Replace every match"},
    },
    "required": ["path", "old_string", "new_string"],
}

GLOB_DESCRIPTION = "Find files in the workspace by glob pattern."
GLOB_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "Glob pattern, for example **/*.md"},
    },
    "required": ["pattern"],
}

GREP_DESCRIPTION = "Search workspace files for a regular expression."
GREP_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "Regular expression"},
        "path": {"type": "string", "description": "File or directory to search"},
        "glob": {"type": "string", "description": "Optional file glob filter"},
    },
    "required": ["pattern"],
}


def _path(args: dict[str, Any]) -> str:
    return str(args.get("path") or "").strip()


def _err(exc: BaseException, path: str = "") -> str:
    if isinstance(exc, PathEscapeError):
        return "error: path escapes workspace"
    if isinstance(exc, FileNotFoundError):
        return f"error: file not found: {path}" if path else "error: file not found"
    if isinstance(exc, IsADirectoryError):
        return f"error: is a directory: {path}" if path else "error: is a directory"
    if isinstance(exc, UnicodeDecodeError):
        return f"error: not a text file: {path}" if path else "error: not a text file"
    if isinstance(exc, WorkspaceError):
        return f"error: {exc}"
    return f"error: {exc}"


async def read_file(workspace: Workspace, args: dict[str, Any]) -> str:
    path = _path(args)
    if not path:
        return "error: path is required"
    try:
        text = await workspace.read_text(path)
    except Exception as exc:  # noqa: BLE001
        return _err(exc, path)
    lines = text.splitlines()
    start = int(args["offset"]) if args.get("offset") is not None else 0
    if start < 0:
        start = 0
    if start > len(lines):
        return f"error: offset {start} is beyond end of file ({len(lines)} lines)"
    chunk = lines[start:]
    if args.get("limit") is not None:
        chunk = chunk[: int(args["limit"])]
    if not chunk:
        return "(empty)"
    width = max(4, len(str(start + len(chunk))))
    return "\n".join(f"{i:>{width}}|{line}" for i, line in enumerate(chunk, start=start + 1))


async def write_file(workspace: Workspace, args: dict[str, Any]) -> str:
    path = _path(args)
    if not path:
        return "error: path is required"
    if "content" not in args:
        return "error: content is required"
    content = "" if args.get("content") is None else str(args.get("content"))
    try:
        await workspace.write_text(path, content)
    except Exception as exc:  # noqa: BLE001
        return _err(exc, path)
    return f"wrote {len(content.encode())} bytes to {path}"


async def edit_file(workspace: Workspace, args: dict[str, Any]) -> str:
    path = _path(args)
    if not path:
        return "error: path is required"
    old = args.get("old_string")
    if old is None or old == "":
        return "error: old_string is required"
    old_s = str(old)
    new_s = "" if args.get("new_string") is None else str(args.get("new_string"))
    replace_all = bool(args.get("replace_all"))
    try:
        text = await workspace.read_text(path)
        count = text.count(old_s)
        if count == 0:
            return "error: old_string not found"
        if count > 1 and not replace_all:
            return (
                f"error: old_string is not unique ({count} matches); "
                "pass replace_all=true or include more context"
            )
        updated = text.replace(old_s, new_s) if replace_all else text.replace(old_s, new_s, 1)
        await workspace.write_text(path, updated)
    except Exception as exc:  # noqa: BLE001
        return _err(exc, path)
    n = count if replace_all else 1
    return f"updated {path} ({n} replacement{'s' if n != 1 else ''})"


async def glob_files(workspace: Workspace, args: dict[str, Any]) -> str:
    pattern = str(args.get("pattern") or "").strip()
    if not pattern:
        return "error: pattern is required"
    try:
        names = await workspace.list_files(pattern)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)
    return "\n".join(names) if names else "No files matched"


async def grep_files(workspace: Workspace, args: dict[str, Any]) -> str:
    raw = args.get("pattern")
    if raw is None or str(raw) == "":
        return "error: pattern is required"
    try:
        rx = re.compile(str(raw))
    except re.error as exc:
        return f"error: invalid regex: {exc}"
    path = str(args.get("path") or "").strip() or "."
    file_glob = str(args.get("glob") or "").strip() or "**/*"
    hits: list[str] = []
    try:
        files = await _grep_targets(workspace, path, file_glob)
        for name in files:
            try:
                text = await workspace.read_text(name)
            except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError, WorkspaceError):
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if rx.search(line):
                    hits.append(f"{name}:{i}:{line}")
                    if len(hits) >= 200:
                        hits.append("... truncated")
                        return "\n".join(hits)
    except Exception as exc:  # noqa: BLE001
        return _err(exc, path)
    return "\n".join(hits) if hits else "No matches"


async def _grep_targets(workspace: Workspace, path: str, file_glob: str) -> list[str]:
    if path not in {".", ""}:
        try:
            await workspace.read_text(path)
            return [path]
        except IsADirectoryError:
            pass
        except FileNotFoundError:
            pass
        except PathEscapeError:
            raise
    names = await workspace.list_files(file_glob)
    if path in {".", ""}:
        return names
    prefix = path.rstrip("/") + "/"
    return [name for name in names if name == path or name.startswith(prefix)]
