from __future__ import annotations

from dataclasses import dataclass

from agent_service.sources.catalog import IndexEntry, upsert_entry
from agent_service.workspace.protocol import Workspace
from research_engine.types import ToolCall

SKIP_SPILL = frozenset({"web_search", "web_fetch"})
HEAD_CHARS = 4000
TAIL_CHARS = 2000


@dataclass
class Overflow:
    workspace: Workspace | None
    run_id: str
    max_chars: int = 10000
    always_store: bool = False

    async def apply(self, call: ToolCall, text: str) -> str:
        if call.name in SKIP_SPILL:
            return text
        body = text or ""
        short = len(body) <= self.max_chars
        if short and not self.always_store:
            return body
        path = f"tool-output/{self.run_id}/{call.id}.txt"
        stored = False
        if self.workspace is not None and self.run_id and call.id:
            try:
                await self.workspace.write_text(path, body)
                stored = True
            except Exception:
                stored = False
            if stored and not short:
                try:
                    await upsert_entry(
                        self.workspace,
                        IndexEntry(id=call.id, tool=call.name, title=_title(call.name, body), path=path),
                    )
                except Exception:
                    pass
                return _head_tail(body, path)
            if stored:
                return body
        if short:
            return body
        return _truncate_only(body, self.max_chars)


def _title(tool: str, body: str) -> str:
    line = ""
    for raw in body.splitlines():
        stripped = raw.strip()
        if stripped:
            line = stripped
            break
    if len(line) > 80:
        line = line[:77] + "..."
    return line or tool


def _head_tail(text: str, path: str) -> str:
    head = text[:HEAD_CHARS]
    tail = text[-TAIL_CHARS:] if len(text) > HEAD_CHARS + TAIL_CHARS else ""
    omitted = max(0, len(text) - len(head) - len(tail))
    parts = [
        head.rstrip(),
        "",
        f"[{omitted} chars omitted. Full text is at {path}; the middle is not empty. Use Read or Grep.]",
    ]
    if tail:
        parts.extend(["", tail.lstrip()])
    return "\n".join(parts)


def _truncate_only(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return (
        text[:max_chars].rstrip()
        + "\n\n[truncated; full result was not saved]"
    )
