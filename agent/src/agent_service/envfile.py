from __future__ import annotations

import os
import re
from pathlib import Path

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def load_repo_env(path: Path | None = None) -> None:
    """Load the repo `.env` without overriding variables already in the process."""
    file = path if path is not None else default_env_path()
    if file is None or not file.is_file():
        return
    for key, value in parse_env(file.read_text(encoding="utf-8")):
        os.environ.setdefault(key, value)


def default_env_path() -> Path | None:
    start = Path(__file__).resolve()
    for parent in start.parents:
        if (parent / "agent" / "pyproject.toml").is_file() and (parent / "backend").is_dir():
            return parent / ".env"
    cwd = Path.cwd()
    if (cwd / "agent" / "pyproject.toml").is_file():
        return cwd / ".env"
    if (cwd / "pyproject.toml").is_file() and (cwd.name == "agent"):
        return cwd.parent / ".env"
    return None


def parse_env(text: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not _KEY.fullmatch(key):
            continue
        rows.append((key, _unquote(value.strip())))
    return rows


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
