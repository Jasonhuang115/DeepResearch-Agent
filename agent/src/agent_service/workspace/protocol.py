from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class WorkspaceError(Exception):
    """User-facing workspace failure."""


class PathEscapeError(WorkspaceError):
    def __init__(self) -> None:
        super().__init__("path escapes workspace")


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    timeout_sec: int = 0


class Workspace(Protocol):
    notice: str | None

    async def read_text(self, path: str) -> str: ...

    async def write_text(self, path: str, content: str) -> None: ...

    async def write_bytes(self, path: str, data: bytes) -> None: ...

    async def list_files(self, pattern: str = "**/*") -> list[str]: ...

    async def run(self, command: str, *, timeout_sec: int = 30) -> RunResult: ...

    async def keepalive(self) -> None: ...


class WorkspaceProvider(Protocol):
    async def ensure(self, conversation_id: str) -> Workspace: ...


class SandboxIdStore(Protocol):
    async def get(self, conversation_id: str) -> str | None: ...

    async def set(self, conversation_id: str, sandbox_id: str, ttl_sec: int = 0) -> None: ...

    async def delete(self, conversation_id: str) -> None: ...


class E2BClient(Protocol):
    sandbox_id: str

    async def read(self, abs_path: str) -> str: ...

    async def write(self, abs_path: str, content: str | bytes) -> None: ...

    async def list_files(self, root: str) -> list[str]: ...

    async def run(self, command: str, timeout_sec: int, cwd: str) -> RunResult: ...

    async def set_timeout(self, timeout_sec: int) -> None: ...


class E2BFactory(Protocol):
    async def create(self, timeout_sec: int) -> E2BClient: ...

    async def connect(self, sandbox_id: str) -> E2BClient: ...
