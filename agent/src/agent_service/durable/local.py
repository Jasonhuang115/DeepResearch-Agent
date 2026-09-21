from __future__ import annotations

import asyncio
from pathlib import Path


class LocalDiskStore:
    """On-disk stand-in for OSS. Keys map 1:1 under root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        rel = (key or "").replace("\\", "/").lstrip("/")
        if not rel or rel.endswith("/") or ".." in rel.split("/"):
            raise ValueError("invalid object key")
        root_r = self.root.resolve()
        target = (root_r / rel).resolve()
        try:
            target.relative_to(root_r)
        except ValueError as exc:
            raise ValueError("invalid object key") from exc
        return target

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        await asyncio.to_thread(_write)

    async def get(self, key: str) -> bytes | None:
        path = self._path(key)

        def _read() -> bytes | None:
            if not path.is_file():
                return None
            return path.read_bytes()

        return await asyncio.to_thread(_read)

    async def list(self, prefix: str) -> list[str]:
        pref = (prefix or "").replace("\\", "/").lstrip("/")
        root_r = self.root.resolve()

        def _list() -> list[str]:
            if not root_r.exists():
                return []
            out: list[str] = []
            for item in root_r.rglob("*"):
                if not item.is_file():
                    continue
                rel = item.relative_to(root_r).as_posix()
                if rel.startswith(pref):
                    out.append(rel)
            return sorted(out)

        return await asyncio.to_thread(_list)

    async def delete_prefix(self, prefix: str) -> None:
        pref = (prefix or "").replace("\\", "/").lstrip("/")
        if not pref:
            raise ValueError("refusing to delete empty prefix")
        root_r = self.root.resolve()
        base = (root_r / pref).resolve() if not pref.endswith("/") else (root_r / pref.rstrip("/")).resolve()

        def _delete() -> None:
            if not root_r.exists():
                return
            if base.exists() and base.is_dir():
                try:
                    base.relative_to(root_r)
                except ValueError:
                    return
                _rmtree(base)
                return
            for item in list(root_r.rglob("*")):
                if not item.is_file():
                    continue
                rel = item.relative_to(root_r).as_posix()
                if rel.startswith(pref):
                    item.unlink(missing_ok=True)

        await asyncio.to_thread(_delete)


def _rmtree(path: Path) -> None:
    for child in path.iterdir():
        if child.is_dir():
            _rmtree(child)
        else:
            child.unlink(missing_ok=True)
    path.rmdir()
