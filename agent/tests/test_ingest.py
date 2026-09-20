from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter

from agent_service.config import settings
from agent_service.sources.ingest import extract_upload, ingest_attachments
from agent_service.sources.ledger import SourceLedger
from agent_service.tools.fs import edit_file, write_file
from agent_service.workspace.local import LocalProvider


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _docx(text: str) -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph(text)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.fixture
async def ws(tmp_path: Path):
    return await LocalProvider(tmp_path).ensure("conv_up")


@pytest.mark.asyncio
async def test_ingest_txt_and_docx(tmp_path: Path, ws, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    up = tmp_path / "uploads"
    up.mkdir()
    (up / "att_txt").write_text("hello notes", encoding="utf-8")
    (up / "att_docx").write_bytes(_docx("Board minutes 2024"))
    ledger = SourceLedger(ws)
    cmd = {
        "request": {
            "content": "summarize",
            "attachments": [
                {
                    "id": "att_txt",
                    "filename": "notes.txt",
                    "content_type": "text/plain",
                    "path": str(up / "att_txt"),
                    "size": 11,
                },
                {
                    "id": "att_docx",
                    "filename": "minutes.docx",
                    "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "path": str(up / "att_docx"),
                    "size": 1,
                },
            ],
        }
    }
    manifest = await ingest_attachments(cmd, ws, ledger)
    assert "src_01" in manifest
    assert "src_02" in manifest
    assert "notes.txt" in manifest
    assert "minutes.docx" in manifest
    assert "hello notes" in await ws.read_text("sources/src_01.md")
    assert "Board minutes 2024" in await ws.read_text("sources/src_02.md")
    data = await ledger.load()
    assert data["sources"][0]["provider"] == "upload"
    assert (tmp_path / "conv_up" / "attachments" / "notes.txt").read_text(encoding="utf-8") == "hello notes"


@pytest.mark.asyncio
async def test_ingest_scanned_pdf_fails(tmp_path: Path, ws, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    up = tmp_path / "uploads"
    up.mkdir()
    (up / "att_pdf").write_bytes(_blank_pdf())
    ledger = SourceLedger(ws)
    cmd = {
        "request": {
            "attachments": [
                {
                    "id": "att_pdf",
                    "filename": "scan.pdf",
                    "content_type": "application/pdf",
                    "path": str(up / "att_pdf"),
                }
            ]
        }
    }
    manifest = await ingest_attachments(cmd, ws, ledger)
    assert "failed" in manifest
    data = await ledger.load()
    assert data["sources"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_ingest_path_escape(tmp_path: Path, ws, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("nope", encoding="utf-8")
    ledger = SourceLedger(ws)
    cmd = {
        "request": {
            "attachments": [
                {"id": "x", "filename": "notes.txt", "path": str(secret)},
            ]
        }
    }
    manifest = await ingest_attachments(cmd, ws, ledger)
    assert "escapes" in manifest
    data = await ledger.load()
    assert data["sources"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_attachments_are_read_only(ws) -> None:
    await ws.write_bytes("attachments/a.txt", b"orig")
    assert "read-only" in await write_file(ws, {"path": "attachments/a.txt", "content": "nope"})
    assert "read-only" in await edit_file(
        ws, {"path": "attachments/a.txt", "old_string": "orig", "new_string": "x"}
    )


def test_extract_txt() -> None:
    assert "hi" in extract_upload("a.txt", b"hi")


@pytest.mark.asyncio
async def test_run_research_ingests_before_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_service.llm.base import TurnResult
    from agent_service.llm.mock import ScriptedLLM
    from agent_service.runtime.agent_runner import run_research

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    up = tmp_path / "uploads"
    up.mkdir()
    (up / "att_txt").write_text("alpha claim", encoding="utf-8")

    class Seq:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict]] = []

        async def emit(self, typ: str, payload: dict | None = None) -> None:
            self.events.append((typ, payload or {}))

    seq = Seq()
    cmd = {
        "request": {
            "content": "use the file",
            "attachments": [
                {
                    "id": "att_txt",
                    "filename": "notes.txt",
                    "content_type": "text/plain",
                    "path": str(up / "att_txt"),
                }
            ],
        },
        "messages": [],
        "conversation_id": "conv_up",
        "run_id": "run_up",
    }
    await run_research(
        cmd,
        seq,
        __import__("asyncio").Event(),
        llm=ScriptedLLM([TurnResult(content="cited src_01")]),
        workspace_provider=LocalProvider(tmp_path),
    )
    assert any(t == "source.added" for t, _ in seq.events)
    assert seq.events[-1][1]["status"] == "succeeded"
    assert "alpha claim" in (tmp_path / "conv_up" / "sources" / "src_01.md").read_text(encoding="utf-8")
