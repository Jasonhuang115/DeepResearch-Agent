from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, urlunparse

from agent_service.workspace.protocol import Workspace
from research_engine.types import EventEmitter

LEDGER_PATH = "sources/ledger.json"
SOURCE_DIR = "sources"
ATTACHMENT_DIR = "attachments"


@dataclass
class SourceRecord:
    source_id: str
    url: str
    title: str = ""
    excerpt: str = ""
    retrieved_at: str = ""
    status: str = "ok"
    error: str | None = None
    query: str | None = None
    path: str | None = None
    provider: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return (url or "").strip()
    host = parsed.hostname or ""
    netloc = host.lower()
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), netloc, path, "", parsed.query, ""))


def is_protected_source_path(path: str) -> bool:
    return _under_dir(path, SOURCE_DIR)


def is_protected_attachment_path(path: str) -> bool:
    return _under_dir(path, ATTACHMENT_DIR)


def is_write_protected_path(path: str) -> bool:
    return is_protected_source_path(path) or is_protected_attachment_path(path)


def _under_dir(path: str, directory: str) -> bool:
    rel = (path or "").replace("\\", "/").lstrip("./")
    return rel == directory or rel.startswith(directory + "/")


def source_body_path(source_id: str) -> str:
    return f"{SOURCE_DIR}/{source_id}.md"


class SourceLedger:
    def __init__(self, workspace: Workspace, seq: EventEmitter | None = None) -> None:
        self.workspace = workspace
        self.seq = seq
        self._data: dict[str, Any] | None = None

    async def load(self) -> dict[str, Any]:
        if self._data is not None:
            return self._data
        try:
            raw = await self.workspace.read_text(LEDGER_PATH)
            data = json.loads(raw) if raw.strip() else {}
        except FileNotFoundError:
            data = {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("queries", [])
        data.setdefault("sources", [])
        self._data = data
        return data

    async def record_query(self, query: str, *, result_count: int, provider: str, at: str | None = None) -> None:
        data = await self.load()
        data["queries"].append(
            {
                "query": query,
                "at": at or utc_now(),
                "result_count": result_count,
                "provider": provider,
            }
        )
        await self._flush()

    def find_by_url(self, url: str) -> SourceRecord | None:
        if self._data is None:
            return None
        target = normalize_url(url)
        for item in self._data.get("sources") or []:
            if normalize_url(str(item.get("url") or "")) == target:
                return _record_from_dict(item)
        return None

    def get(self, source_id: str) -> SourceRecord | None:
        if self._data is None:
            return None
        for item in self._data.get("sources") or []:
            if item.get("source_id") == source_id:
                return _record_from_dict(item)
        return None

    async def add(
        self,
        *,
        url: str,
        title: str = "",
        excerpt: str = "",
        status: str = "ok",
        error: str | None = None,
        query: str | None = None,
        provider: str | None = None,
        body: str | None = None,
        source_id: str | None = None,
        emit: bool = True,
    ) -> SourceRecord:
        data = await self.load()
        existing = self.find_by_url(url) if url else None
        sid = source_id or (existing.source_id if existing else self._next_id(data))
        record = SourceRecord(
            source_id=sid,
            url=url,
            title=title or (existing.title if existing else ""),
            excerpt=(excerpt or (existing.excerpt if existing else ""))[:800],
            retrieved_at=utc_now(),
            status=status,
            error=error,
            query=query if query is not None else (existing.query if existing else None),
            path=existing.path if existing else None,
            provider=provider or (existing.provider if existing else None),
        )
        if body is not None and status != "failed":
            await self.workspace.write_text(source_body_path(sid), body)
            record.path = source_body_path(sid)
        payload = asdict(record)
        sources = data["sources"]
        for i, item in enumerate(sources):
            if item.get("source_id") == sid:
                sources[i] = payload
                break
        else:
            sources.append(payload)
        await self._flush()
        if emit and status == "ok" and self.seq is not None:
            await self.seq.emit(
                "source.added",
                {"source_id": record.source_id, "url": record.url, "title": record.title},
            )
        return record

    def _next_id(self, data: dict[str, Any]) -> str:
        n = 1
        for item in data.get("sources") or []:
            raw = str(item.get("source_id") or "")
            if raw.startswith("src_"):
                try:
                    n = max(n, int(raw.split("_", 1)[1]) + 1)
                except ValueError:
                    continue
        return f"src_{n:02d}"

    async def _flush(self) -> None:
        data = await self.load()
        await self.workspace.write_text(LEDGER_PATH, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _record_from_dict(item: dict[str, Any]) -> SourceRecord:
    return SourceRecord(
        source_id=str(item.get("source_id") or ""),
        url=str(item.get("url") or ""),
        title=str(item.get("title") or ""),
        excerpt=str(item.get("excerpt") or ""),
        retrieved_at=str(item.get("retrieved_at") or ""),
        status=str(item.get("status") or "ok"),
        error=item.get("error"),
        query=item.get("query"),
        path=item.get("path"),
        provider=item.get("provider"),
    )
