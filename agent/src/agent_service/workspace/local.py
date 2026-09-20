from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from agent_service.workspace.paths import (
    clean_env,
    reject_escape_pattern,
    resolve_in_root,
    safe_conversation_id,
)
from agent_service.workspace.protocol import RunResult


@dataclass
class LocalDirWorkspace:
    root: Path
    notice: str | None = None
    default_timeout_sec: int = 30

    async def read_text(self, path: str) -> str:
        target = resolve_in_root(self.root, path)
        return await asyncio.to_thread(_read_text, target)

    async def write_text(self, path: str, content: str) -> None:
        target = resolve_in_root(self.root, path)
        await asyncio.to_thread(_write_text, target, content)

    async def write_bytes(self, path: str, data: bytes) -> None:
        target = resolve_in_root(self.root, path)
        await asyncio.to_thread(_write_bytes, target, data)

    async def list_files(self, pattern: str = "**/*") -> list[str]:
        pat = reject_escape_pattern(pattern)
        return await asyncio.to_thread(_list_files, self.root, pat)

    async def run(self, command: str, *, timeout_sec: int = 30) -> RunResult:
        limit = timeout_sec or self.default_timeout_sec
        return await asyncio.to_thread(_run, command, self.root, limit)

    async def keepalive(self) -> None:
        return None


@dataclass
class LocalProvider:
    base: Path
    notice: str | None = field(default=None)

    async def ensure(self, conversation_id: str) -> LocalDirWorkspace:
        cid = safe_conversation_id(conversation_id)
        root = self.base / cid
        await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
        return LocalDirWorkspace(root=root.resolve(), notice=self.notice)


def _read_text(path: Path) -> str:
    if path.is_dir():
        raise IsADirectoryError(path)
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _list_files(root: Path, pattern: str) -> list[str]:
    root_r = root.resolve()
    found: set[str] = set()
    for item in root_r.glob(pattern):
        if not item.is_file():
            continue
        resolved = item.resolve()
        try:
            found.add(resolved.relative_to(root_r).as_posix())
        except ValueError:
            continue
    return sorted(found)


def _run(command: str, cwd: Path, timeout_sec: int) -> RunResult:
    bash = "/bin/bash" if os.path.exists("/bin/bash") else None
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd.resolve()),
            env=clean_env(),
            timeout=timeout_sec,
            capture_output=True,
            text=True,
            executable=bash,
        )
    except subprocess.TimeoutExpired:
        return RunResult(exit_code=-1, timed_out=True, timeout_sec=timeout_sec)
    return RunResult(
        exit_code=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        timeout_sec=timeout_sec,
    )
