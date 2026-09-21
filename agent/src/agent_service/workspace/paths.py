from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from agent_service.workspace.protocol import PathEscapeError, RunResult, WorkspaceError

_CID = re.compile(r"^[A-Za-z0-9._-]+$")
_SECRET_RE = re.compile(r"(API_KEY|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|PRIVATE_KEY)$", re.I)
_EXPLICIT_SECRETS = frozenset(
    {
        "E2B_API_KEY",
        "OPENAI_API_KEY",
        "TAVILY_API_KEY",
        "OSS_ACCESS_KEY_ID",
        "OSS_ACCESS_KEY_SECRET",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    }
)


def safe_conversation_id(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return "default"
    if _CID.fullmatch(text) and ".." not in text:
        return text
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"c_{digest}"


def resolve_in_root(root: Path, user_path: str) -> Path:
    raw = (user_path or "").strip()
    if not raw:
        raise WorkspaceError("path is required")
    root_r = root.resolve()
    candidate = Path(raw)
    resolved = candidate.resolve() if candidate.is_absolute() else (root_r / raw).resolve()
    try:
        resolved.relative_to(root_r)
    except ValueError as exc:
        raise PathEscapeError from exc
    return resolved


def resolve_posix(root: str, user_path: str) -> str:
    raw = (user_path or "").strip()
    if not raw:
        raise WorkspaceError("path is required")
    if raw.startswith("~"):
        raise PathEscapeError
    root_n = os.path.normpath(root)
    joined = os.path.normpath(raw if raw.startswith("/") else f"{root_n}/{raw}")
    if joined != root_n and not joined.startswith(root_n + "/"):
        raise PathEscapeError
    return joined


def rel_posix(root: str, abs_path: str) -> str:
    return os.path.relpath(os.path.normpath(abs_path), os.path.normpath(root)).replace("\\", "/")


def reject_escape_pattern(pattern: str) -> str:
    raw = (pattern or "").strip() or "**/*"
    if raw.startswith("/") or raw.startswith("~") or ".." in Path(raw).parts:
        raise PathEscapeError
    return raw


def glob_match(rel: str, pattern: str) -> bool:
    rel_n = rel.replace("\\", "/").lstrip("./")
    pat = reject_escape_pattern(pattern).replace("\\", "/").lstrip("./")
    rx = _glob_to_re(pat)
    if rx.fullmatch(rel_n):
        return True
    name = rel_n.rsplit("/", 1)[-1]
    return bool(rx.fullmatch(name))


def _glob_to_re(pattern: str) -> re.Pattern[str]:
    i = 0
    out: list[str] = []
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def clean_env(src: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if src is None else src)
    for key in list(env):
        if key in _EXPLICIT_SECRETS or _SECRET_RE.search(key):
            env.pop(key, None)
    return env


def format_run(result: RunResult) -> str:
    if result.timed_out:
        return f"error: timed out after {result.timeout_sec}s"
    parts: list[str] = []
    if result.exit_code != 0:
        parts.append(f"exit_code: {result.exit_code}")
    if result.stdout:
        parts.append(result.stdout.rstrip("\n"))
    if result.stderr:
        parts.append(result.stderr.rstrip("\n"))
    return "\n".join(parts) if parts else "(no output)"
