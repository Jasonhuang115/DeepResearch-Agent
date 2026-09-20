from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter

from agent_service.sources.ledger import SourceLedger
from agent_service.tools.ssrf import blocked_reason
from agent_service.tools.web_fetch import HttpReply, web_fetch
from agent_service.workspace.local import LocalProvider


async def public_resolve(_host: str) -> list[str]:
    return ["8.8.8.8"]


class ScriptedGetter:
    def __init__(self, replies: dict[str, HttpReply]) -> None:
        self.replies = replies
        self.urls: list[str] = []

    async def __call__(self, url: str, *, timeout: float = 20) -> HttpReply:
        self.urls.append(url)
        if url not in self.replies:
            return HttpReply(404, {}, b"missing")
        return self.replies[url]


@pytest.fixture
async def ledger(tmp_path: Path) -> SourceLedger:
    ws = await LocalProvider(tmp_path).ensure("conv")
    return SourceLedger(ws)


@pytest.mark.asyncio
async def test_fetch_html_writes_source(ledger: SourceLedger) -> None:
    events: list[tuple[str, dict]] = []

    class Seq:
        async def emit(self, typ: str, payload: dict | None = None) -> None:
            events.append((typ, payload or {}))

    ledger.seq = Seq()
    html = (
        "<html><head><title>IR page</title><script>alert(1)</script></head>"
        "<body><nav>skip</nav><p>Visible claim.</p></body></html>"
    )
    getter = ScriptedGetter(
        {"https://example.com/ir": HttpReply(200, {"content-type": "text/html"}, html.encode())}
    )
    text = await web_fetch(
        ledger.workspace, ledger, {"url": "https://example.com/ir"}, getter=getter, resolve=public_resolve
    )
    assert "src_01" in text
    assert "Visible claim." in text
    assert "alert(1)" not in text
    assert "skip" not in text
    body = await ledger.workspace.read_text("sources/src_01.md")
    assert "Visible claim." in body
    assert events[0][0] == "source.added"
    assert events[0][1]["source_id"] == "src_01"


@pytest.mark.asyncio
async def test_fetch_failures_are_errors(ledger: SourceLedger) -> None:
    getter = ScriptedGetter(
        {"https://example.com/gone": HttpReply(404, {"content-type": "text/plain"}, b"nope")}
    )
    text = await web_fetch(
        ledger.workspace, ledger, {"url": "https://example.com/gone"}, getter=getter, resolve=public_resolve
    )
    assert text.startswith("error: HTTP 404")
    data = await ledger.load()
    assert data["sources"][0]["status"] == "failed"
    assert data["sources"][0]["error"] == "HTTP 404"


@pytest.mark.asyncio
async def test_ssrf_blocks_file_and_loopback(ledger: SourceLedger) -> None:
    getter = ScriptedGetter({})
    assert "only http/https" in await web_fetch(
        ledger.workspace, ledger, {"url": "file:///etc/passwd"}, getter=getter
    )
    assert "blocked" in await web_fetch(
        ledger.workspace, ledger, {"url": "http://127.0.0.1/secret"}, getter=getter
    )
    assert "blocked" in await web_fetch(
        ledger.workspace, ledger, {"url": "http://localhost/secret"}, getter=getter
    )
    assert getter.urls == []


@pytest.mark.asyncio
async def test_redirect_to_private_is_blocked(ledger: SourceLedger) -> None:
    getter = ScriptedGetter(
        {
            "https://example.com/go": HttpReply(302, {"location": "http://169.254.169.254/"}, b""),
        }
    )
    text = await web_fetch(
        ledger.workspace, ledger, {"url": "https://example.com/go"}, getter=getter, resolve=public_resolve
    )
    assert "blocked" in text
    assert "169.254.169.254" in text


@pytest.mark.asyncio
async def test_empty_pdf_is_explicit_failure(ledger: SourceLedger) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = BytesIO()
    writer.write(buf)
    getter = ScriptedGetter(
        {
            "https://example.com/scan.pdf": HttpReply(
                200, {"content-type": "application/pdf"}, buf.getvalue()
            )
        }
    )
    text = await web_fetch(
        ledger.workspace,
        ledger,
        {"url": "https://example.com/scan.pdf"},
        getter=getter,
        resolve=public_resolve,
    )
    assert "unable to extract" in text


def test_blocked_reason_helpers() -> None:
    assert blocked_reason("ftp://example.com") is not None
    assert blocked_reason("https://metadata.google.internal/") is not None
    assert blocked_reason("https://example.com/ok") is None
    assert blocked_reason("http://198.18.0.92/") is not None
    assert blocked_reason("https://www.jiemian.com/a", resolved_ips=["198.18.0.92"]) is None
    assert blocked_reason("https://www.jiemian.com/a", resolved_ips=["10.0.0.8"]) is not None


@pytest.mark.asyncio
async def test_clash_fake_ip_resolve_still_fetches(ledger: SourceLedger) -> None:
    async def fake_ip_resolve(_host: str) -> list[str]:
        return ["198.18.0.92"]

    getter = ScriptedGetter(
        {"https://www.jiemian.com/a": HttpReply(200, {"content-type": "text/plain"}, b"ok body")}
    )
    text = await web_fetch(
        ledger.workspace,
        ledger,
        {"url": "https://www.jiemian.com/a"},
        getter=getter,
        resolve=fake_ip_resolve,
    )
    assert "ok body" in text
    assert getter.urls == ["https://www.jiemian.com/a"]
