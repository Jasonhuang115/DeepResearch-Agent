from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from agent_service.config import resolve_durable_root, settings
from agent_service.durable.local import LocalDiskStore

log = logging.getLogger("agent_service.durable")


class AliyunOSSStore:
    def __init__(self, bucket: Any) -> None:
        self._bucket = bucket

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self._bucket.put_object, key, data)

    async def get(self, key: str) -> bytes | None:
        def _get() -> bytes | None:
            try:
                result = self._bucket.get_object(key)
            except Exception as exc:  # noqa: BLE001
                name = type(exc).__name__
                if "NoSuchKey" in name or "NotFound" in name:
                    return None
                status = getattr(exc, "status", None)
                if status == 404:
                    return None
                raise
            return result.read()

        return await asyncio.to_thread(_get)

    async def list(self, prefix: str) -> list[str]:
        def _list() -> list[str]:
            import oss2

            return [obj.key for obj in oss2.ObjectIterator(self._bucket, prefix=prefix or "")]

        return await asyncio.to_thread(_list)

    async def delete_prefix(self, prefix: str) -> None:
        if not (prefix or "").strip():
            raise ValueError("refusing to delete empty prefix")

        def _delete() -> None:
            import oss2

            keys = [obj.key for obj in oss2.ObjectIterator(self._bucket, prefix=prefix)]
            if keys:
                self._bucket.batch_delete_objects(keys)

        await asyncio.to_thread(_delete)


def build_durable_store(*, root: Path | None = None, bucket: Any | None = None) -> LocalDiskStore | AliyunOSSStore:
    if bucket is not None:
        return AliyunOSSStore(bucket)
    oss_bucket = _try_oss_bucket()
    if oss_bucket is not None:
        return AliyunOSSStore(oss_bucket)
    return LocalDiskStore(root if root is not None else resolve_durable_root())


def _try_oss_bucket() -> Any | None:
    key = (settings.oss_access_key_id or "").strip()
    secret = (settings.oss_access_key_secret or "").strip()
    name = (settings.oss_bucket or "").strip()
    endpoint = (settings.oss_endpoint or "").strip()
    if not (key and secret and name and endpoint):
        return None
    try:
        import oss2
    except ImportError:
        log.warning("OSS credentials set but oss2 is not installed; using local durable store")
        return None
    auth = oss2.Auth(key, secret)
    host = endpoint
    if host.startswith("https://") or host.startswith("http://"):
        return oss2.Bucket(auth, host, name)
    return oss2.Bucket(auth, f"https://{host}", name)
