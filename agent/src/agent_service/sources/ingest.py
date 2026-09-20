from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from agent_service.config import resolve_upload_dir
from agent_service.sources.ledger import ATTACHMENT_DIR, SourceLedger
from agent_service.tools.extract import docx_to_text, looks_like_pdf, pdf_to_text
from agent_service.workspace.protocol import Workspace

_UNSAFE = re.compile(r"[^\w.\-]+", re.UNICODE)


async def ingest_attachments(cmd: dict[str, Any], workspace: Workspace, ledger: SourceLedger) -> str:
    refs = ((cmd.get("request") or {}).get("attachments")) or []
    if not isinstance(refs, list) or not refs:
        return ""
    used: set[str] = set()
    lines: list[str] = ["<attachments>"]
    for raw in refs:
        if not isinstance(raw, dict):
            continue
        filename = str(raw.get("filename") or "file")
        att_id = str(raw.get("id") or "")
        ctype = str(raw.get("content_type") or "")
        url = f"attachment://{att_id}/{filename}" if att_id else f"attachment://{filename}"
        safe = _unique_name(filename, used)
        rel = f"{ATTACHMENT_DIR}/{safe}"
        try:
            data = _read_upload_bytes(str(raw.get("path") or ""))
            await workspace.write_bytes(rel, data)
        except Exception as exc:  # noqa: BLE001
            record = await ledger.add(
                url=url,
                title=filename,
                status="failed",
                error=str(exc),
                provider="upload",
                emit=False,
            )
            lines.append(f"- {record.source_id} {filename} failed: {exc}")
            continue
        try:
            text = extract_upload(filename, data, ctype)
        except Exception as exc:  # noqa: BLE001
            record = await ledger.add(
                url=url,
                title=filename,
                status="failed",
                error=str(exc),
                provider="upload",
                emit=False,
            )
            lines.append(f"- {record.source_id} {filename} failed: {exc}")
            continue
        body = f"# {filename}\n\nURL: {url}\n\n{text}\n"
        record = await ledger.add(
            url=url,
            title=filename,
            excerpt=text[:400].strip(),
            status="ok",
            provider="upload",
            body=body,
        )
        path = record.path or f"sources/{record.source_id}.md"
        lines.append(f"- {record.source_id} {filename} ({ctype or 'unknown'}) {rel} {path}")
    if len(lines) == 1:
        return ""
    lines.append("</attachments>")
    return "\n".join(lines)


def extract_upload(filename: str, data: bytes, content_type: str = "") -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf" or looks_like_pdf(data, content_type):
        return pdf_to_text(data)
    if ext == ".docx":
        return docx_to_text(data)
    if ext in {".txt", ".md", ".csv"}:
        text = data.decode("utf-8")
        if not text.strip():
            raise ValueError("file is empty")
        return text
    raise ValueError(f"unsupported type: {filename}")


def _read_upload_bytes(raw: str) -> bytes:
    if not raw.strip():
        raise ValueError("attachment path is required")
    root = os.path.realpath(resolve_upload_dir())
    path = Path(raw)
    if not path.is_absolute():
        path = Path(root) / path
    resolved = os.path.realpath(path)
    if resolved != root and not resolved.startswith(root + os.sep):
        raise ValueError("path escapes upload dir")
    return Path(resolved).read_bytes()


def _unique_name(filename: str, used: set[str]) -> str:
    base = Path(str(filename).replace("\\", "/")).name.strip()
    base = base.replace("\x00", "")
    if not base or base in {".", ".."}:
        base = "file"
    stem, ext = os.path.splitext(base)
    stem = _UNSAFE.sub("_", stem).strip("._") or "file"
    ext = ext.lower()
    out = f"{stem}{ext}"
    n = 2
    while out in used:
        out = f"{stem}-{n}{ext}"
        n += 1
    used.add(out)
    return out
