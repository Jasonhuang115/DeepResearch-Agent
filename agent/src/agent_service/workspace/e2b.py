from __future__ import annotations

import logging
import os
import shlex
from dataclasses import dataclass, field

from agent_service.workspace.paths import glob_match, reject_escape_pattern, resolve_posix
from agent_service.workspace.protocol import (
    E2BClient,
    E2BFactory,
    RunResult,
    SandboxIdStore,
    WorkspaceError,
)
from agent_service.workspace.local import LocalDirWorkspace, LocalProvider
from agent_service.workspace.store import MemorySandboxIdStore

log = logging.getLogger("agent_service.workspace.e2b")

E2B_HOME = "/home/user"
LOST_NOTICE = "Previous workspace could not be reconnected; this is a new empty workspace."
FALLBACK_NOTICE = "Isolated sandbox unavailable; using the local workspace."


@dataclass
class E2BWorkspace:
    client: E2BClient
    home: str = E2B_HOME
    notice: str | None = None
    timeout_sec: int = 3600

    async def read_text(self, path: str) -> str:
        target = resolve_posix(self.home, path)
        try:
            return await self.client.read(target)
        except FileNotFoundError:
            raise
        except Exception as exc:
            msg = str(exc).lower()
            if "not found" in msg or "no such file" in msg:
                raise FileNotFoundError(target) from exc
            if "is a directory" in msg:
                raise IsADirectoryError(target) from exc
            raise WorkspaceError(str(exc)) from exc

    async def write_text(self, path: str, content: str) -> None:
        target = resolve_posix(self.home, path)
        await self.client.write(target, content)

    async def write_bytes(self, path: str, data: bytes) -> None:
        target = resolve_posix(self.home, path)
        await self.client.write(target, data)

    async def list_files(self, pattern: str = "**/*") -> list[str]:
        pat = reject_escape_pattern(pattern)
        names = await self.client.list_files(self.home)
        return sorted(name.replace("\\", "/") for name in names if glob_match(name, pat))

    async def run(self, command: str, *, timeout_sec: int = 30) -> RunResult:
        return await self.client.run(command, timeout_sec or 30, self.home)

    async def keepalive(self) -> None:
        await self.client.set_timeout(self.timeout_sec)


@dataclass
class E2BProvider:
    factory: E2BFactory
    store: SandboxIdStore = field(default_factory=MemorySandboxIdStore)
    local: LocalProvider | None = None
    timeout_sec: int = 3600
    ttl_sec: int = 3300
    home: str = E2B_HOME

    async def ensure(self, conversation_id: str) -> E2BWorkspace | LocalDirWorkspace:
        try:
            return await self._ensure_e2b(conversation_id)
        except Exception:
            log.exception("E2B ensure failed; falling back to local workspace")
            if self.local is None:
                raise
            ws = await self.local.ensure(conversation_id)  # type: ignore[union-attr]
            extra = FALLBACK_NOTICE
            ws.notice = f"{ws.notice}\n{extra}".strip() if ws.notice else extra
            return ws

    async def _ensure_e2b(self, conversation_id: str) -> E2BWorkspace:
        notice: str | None = None
        sandbox_id = await self.store.get(conversation_id)
        if sandbox_id:
            try:
                client = await self.factory.connect(sandbox_id)
                return E2BWorkspace(client=client, home=self.home, timeout_sec=self.timeout_sec)
            except Exception:
                log.info("E2B connect failed for %s; recreating", conversation_id)
                await self.store.delete(conversation_id)
                notice = LOST_NOTICE
        client = await self.factory.create(self.timeout_sec)
        await self.store.set(conversation_id, client.sandbox_id, self.ttl_sec)
        return E2BWorkspace(client=client, home=self.home, notice=notice, timeout_sec=self.timeout_sec)


class SDKSandbox:
    def __init__(self, raw: object) -> None:
        self._raw = raw

    @property
    def sandbox_id(self) -> str:
        return str(getattr(self._raw, "sandbox_id", None) or getattr(self._raw, "id"))

    async def read(self, abs_path: str) -> str:
        data = await self._raw.files.read(abs_path)  # type: ignore[attr-defined]
        if isinstance(data, bytes):
            return data.decode("utf-8")
        return str(data)

    async def write(self, abs_path: str, content: str | bytes) -> None:
        parent = os.path.dirname(abs_path)
        if parent and parent not in {"/", self._home()}:
            mkdir = getattr(getattr(self._raw, "files", None), "make_dir", None)
            if mkdir is not None:
                try:
                    await mkdir(parent)
                except Exception:
                    pass
        await self._raw.files.write(abs_path, content)  # type: ignore[attr-defined]

    def _home(self) -> str:
        return E2B_HOME

    async def list_files(self, root: str) -> list[str]:
        script = (
            "import os\n"
            f"root = {root!r}\n"
            "for dp, _, fns in os.walk(root):\n"
            "    for fn in fns:\n"
            "        print(os.path.relpath(os.path.join(dp, fn), root))\n"
        )
        result = await self.run(f"python3 -c {shlex.quote(script)}", 30, root)
        if result.exit_code != 0:
            return []
        return [line.replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]

    async def run(self, command: str, timeout_sec: int, cwd: str) -> RunResult:
        raw = await self._raw.commands.run(command, timeout=timeout_sec, cwd=cwd)  # type: ignore[attr-defined]
        return RunResult(
            exit_code=int(getattr(raw, "exit_code", 0) or 0),
            stdout=getattr(raw, "stdout", "") or "",
            stderr=getattr(raw, "stderr", "") or "",
            timeout_sec=timeout_sec,
        )

    async def set_timeout(self, timeout_sec: int) -> None:
        fn = getattr(self._raw, "set_timeout", None)
        if fn is None:
            return
        await fn(timeout_sec)

    async def kill(self) -> None:
        fn = getattr(self._raw, "kill", None)
        if fn is None:
            return
        await fn()


class SDKFactory:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def create(self, timeout_sec: int) -> SDKSandbox:
        raw = await self._cls().create(api_key=self.api_key, timeout=timeout_sec)
        return SDKSandbox(raw)

    async def connect(self, sandbox_id: str) -> SDKSandbox:
        cls = self._cls()
        connect = getattr(cls, "_cls_connect_sandbox", None) or cls.connect
        raw = await connect(sandbox_id, api_key=self.api_key)
        return SDKSandbox(raw)

    @staticmethod
    def _cls():
        from e2b import AsyncSandbox

        return AsyncSandbox


def try_sdk_factory(api_key: str) -> E2BFactory | None:
    try:
        factory = SDKFactory(api_key)
        factory._cls()
    except Exception:
        log.warning("e2b package is not available")
        return None
    return factory


@dataclass
class FakeE2BSandbox:
    sandbox_id: str
    fs: dict[str, str | bytes] = field(default_factory=dict)
    timeout: int = 3600

    async def read(self, abs_path: str) -> str:
        path = os.path.normpath(abs_path)
        if path not in self.fs:
            raise FileNotFoundError(path)
        data = self.fs[path]
        if isinstance(data, bytes):
            return data.decode("utf-8")
        return data

    async def write(self, abs_path: str, content: str | bytes) -> None:
        self.fs[os.path.normpath(abs_path)] = content

    async def list_files(self, root: str) -> list[str]:
        root_n = os.path.normpath(root)
        out: list[str] = []
        for path in self.fs:
            pn = os.path.normpath(path)
            if pn == root_n or pn.startswith(root_n + "/"):
                rel = os.path.relpath(pn, root_n).replace("\\", "/")
                if rel != ".":
                    out.append(rel)
        return sorted(out)

    async def run(self, command: str, timeout_sec: int, cwd: str) -> RunResult:
        if command.startswith("echo "):
            return RunResult(exit_code=0, stdout=command[5:] + "\n", timeout_sec=timeout_sec)
        return RunResult(exit_code=0, stdout="", timeout_sec=timeout_sec)

    async def set_timeout(self, timeout_sec: int) -> None:
        self.timeout = timeout_sec


@dataclass
class FakeE2BFactory:
    sandboxes: dict[str, FakeE2BSandbox] = field(default_factory=dict)
    fail_connect: bool = False
    fail_create: bool = False
    _n: int = 0

    async def create(self, timeout_sec: int) -> FakeE2BSandbox:
        if self.fail_create:
            raise RuntimeError("e2b create failed")
        self._n += 1
        sandbox = FakeE2BSandbox(sandbox_id=f"sb_{self._n}", timeout=timeout_sec)
        self.sandboxes[sandbox.sandbox_id] = sandbox
        return sandbox

    async def connect(self, sandbox_id: str) -> FakeE2BSandbox:
        if self.fail_connect or sandbox_id not in self.sandboxes:
            raise ConnectionError("sandbox gone")
        return self.sandboxes[sandbox_id]
