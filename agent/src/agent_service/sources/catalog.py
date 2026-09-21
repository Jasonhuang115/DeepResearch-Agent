from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from agent_service.workspace.protocol import Workspace

INDEX_PATH = "sources/index.json"


@dataclass
class IndexEntry:
    id: str
    tool: str
    title: str
    path: str


async def load_index(workspace: Workspace) -> list[IndexEntry]:
    try:
        raw = await workspace.read_text(INDEX_PATH)
        data = json.loads(raw) if raw.strip() else {}
    except FileNotFoundError:
        return []
    except Exception:
        return []
    rows = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[IndexEntry] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        ident = str(item.get("id") or "").strip()
        if not path or not ident:
            continue
        out.append(
            IndexEntry(
                id=ident,
                tool=str(item.get("tool") or "").strip() or "unknown",
                title=str(item.get("title") or "").strip(),
                path=path,
            )
        )
    return out


async def save_index(workspace: Workspace, entries: list[IndexEntry]) -> None:
    payload = {"entries": [asdict(e) for e in entries]}
    await workspace.write_text(INDEX_PATH, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


async def upsert_entry(workspace: Workspace, entry: IndexEntry) -> None:
    if not entry.path:
        return
    entries = await load_index(workspace)
    for i, existing in enumerate(entries):
        if existing.id == entry.id:
            entries[i] = entry
            break
    else:
        entries.append(entry)
    await save_index(workspace, entries)


async def sync_source_entries(workspace: Workspace, sources: list[dict[str, Any]]) -> None:
    existing = await load_index(workspace)
    extras = [e for e in existing if not str(e.id).startswith("src_")]
    rebuilt: list[IndexEntry] = []
    for item in sources:
        path = str(item.get("path") or "").strip()
        sid = str(item.get("source_id") or "").strip()
        if not path or not sid:
            continue
        tool = str(item.get("provider") or "").strip() or "unknown"
        if tool in {"mock", "tavily"}:
            tool = "web_search"
        rebuilt.append(
            IndexEntry(
                id=sid,
                tool=tool,
                title=str(item.get("title") or sid),
                path=path,
            )
        )
    await save_index(workspace, rebuilt + extras)


def render_catalog_chapter(entries: list[IndexEntry]) -> str:
    lines = ["## 工具正文"]
    listed = [e for e in entries if e.path]
    if not listed:
        lines.append("无")
    else:
        for entry in listed:
            title = entry.title or entry.id
            lines.append(f"- {entry.id}  {entry.tool}  {title}  {entry.path}")
        lines.append("全文在上述路径，本章不是原文。")
    return "\n".join(lines)
