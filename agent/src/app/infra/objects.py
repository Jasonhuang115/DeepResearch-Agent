from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from urllib.parse import quote

import oss2

from app.infra.config import Settings, settings


class ObjectStore:
    async def put(self, key: str, data: bytes) -> None:
        raise NotImplementedError

    async def get(self, key: str) -> bytes:
        raise NotImplementedError

    async def exists(self, key: str) -> bool:
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        raise NotImplementedError

    async def delete_prefix(self, prefix: str) -> None:
        raise NotImplementedError

    async def signed_url(self, key: str, expires: int = 300) -> str:
        raise NotImplementedError


class LocalObjectStore(ObjectStore):
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("invalid object key")
        return path

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if await asyncio.to_thread(path.exists):
            await asyncio.to_thread(path.unlink)

    async def delete_prefix(self, prefix: str) -> None:
        path = self._path(prefix.rstrip("/"))
        if await asyncio.to_thread(path.exists):
            await asyncio.to_thread(shutil.rmtree, path)

    async def signed_url(self, key: str, expires: int = 300) -> str:
        _ = expires
        return f"/v1/local-objects/{quote(key)}"


class AliyunObjectStore(ObjectStore):
    def __init__(self, cfg: Settings) -> None:
        if not all(
            [cfg.oss_access_key_id, cfg.oss_access_key_secret, cfg.oss_endpoint, cfg.oss_bucket]
        ):
            raise RuntimeError("OSS configuration is incomplete")
        auth = oss2.Auth(cfg.oss_access_key_id, cfg.oss_access_key_secret)
        self.bucket = oss2.Bucket(auth, cfg.oss_endpoint, cfg.oss_bucket)

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self.bucket.put_object, key, data)

    async def get(self, key: str) -> bytes:
        result = await asyncio.to_thread(self.bucket.get_object, key)
        return await asyncio.to_thread(result.read)

    async def exists(self, key: str) -> bool:
        return bool(await asyncio.to_thread(self.bucket.object_exists, key))

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.bucket.delete_object, key)

    async def delete_prefix(self, prefix: str) -> None:
        def remove() -> None:
            for batch in oss2.ObjectIterator(self.bucket, prefix=prefix):
                self.bucket.delete_object(batch.key)

        await asyncio.to_thread(remove)

    async def signed_url(self, key: str, expires: int = 300) -> str:
        return str(await asyncio.to_thread(self.bucket.sign_url, "GET", key, expires))


def build_object_store(cfg: Settings = settings) -> ObjectStore:
    if cfg.object_store == "oss":
        return AliyunObjectStore(cfg)
    if cfg.object_store == "local":
        return LocalObjectStore(cfg.object_root)
    raise RuntimeError(f"unsupported OBJECT_STORE={cfg.object_store}")


def conversation_prefix(user_id: str, conversation_id: str) -> str:
    return f"users/{user_id}/conversations/{conversation_id}/"


def attachment_key(user_id: str, conversation_id: str, attachment_id: str) -> str:
    return f"{conversation_prefix(user_id, conversation_id)}attachments/{attachment_id}"


def run_key(user_id: str, conversation_id: str, run_id: str, name: str) -> str:
    return f"{conversation_prefix(user_id, conversation_id)}runs/{run_id}/{name}"
