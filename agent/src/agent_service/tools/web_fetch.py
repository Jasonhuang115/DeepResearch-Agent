from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

from agent_service.config import settings
from agent_service.sources.ledger import SourceLedger, source_body_path
from agent_service.tools.extract import html_to_text, looks_like_html, looks_like_pdf, pdf_to_text
from agent_service.tools.ssrf import blocked_reason, is_ip_literal, resolve_host
from agent_service.workspace.protocol import Workspace

DESCRIPTION = "Fetch a URL and save extracted text into the source ledger."
PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "http(s) URL to fetch"},
        "source_id": {"type": "string", "description": "Existing source_id to update"},
    },
    "required": ["url"],
}

Getter = Callable[..., Awaitable["HttpReply"]]


class FetchError(Exception):
    pass


@dataclass
class HttpReply:
    status_code: int
    headers: dict[str, str]
    content: bytes


async def web_fetch(
    workspace: Workspace,
    ledger: SourceLedger,
    args: dict[str, Any],
    *,
    getter: Getter | None = None,
    resolve: Any = None,
) -> str:
    url = str(args.get("url") or "").strip()
    source_id = str(args.get("source_id") or "").strip() or None
    if not url:
        return "error: url is required"
    try:
        final_url, title, text, content_type = await fetch_document(
            url,
            getter=getter,
            timeout=settings.fetch_timeout_sec,
            max_bytes=settings.fetch_max_bytes,
            resolve=resolve or resolve_host,
        )
    except FetchError as exc:
        await ledger.add(
            url=url,
            title=source_id or url,
            status="failed",
            error=str(exc),
            source_id=source_id,
            emit=False,
        )
        return f"error: {exc}"
    except Exception as exc:  # noqa: BLE001
        await ledger.add(
            url=url,
            title=source_id or url,
            status="failed",
            error=str(exc),
            source_id=source_id,
            emit=False,
        )
        return f"error: fetch failed: {exc}"

    excerpt = text[:400].strip()
    body = (
        f"# {title or final_url}\n\n"
        f"URL: {final_url}\n"
        f"Content-Type: {content_type}\n\n"
        f"{text}\n"
    )
    record = await ledger.add(
        url=final_url,
        title=title or final_url,
        excerpt=excerpt,
        status="ok",
        source_id=source_id,
        provider="web_fetch",
        body=body,
    )
    preview = text[:2000].strip()
    extra = ""
    if len(text) > 2000:
        extra = (
            f"\n\n[{len(text)} chars total. Full text is at {record.path}; "
            "the middle is not empty. Use Read or Grep.]"
        )
    return (
        f"source_id: {record.source_id}\n"
        f"title: {record.title}\n"
        f"url: {record.url}\n"
        f"path: {record.path or source_body_path(record.source_id)}\n\n"
        f"{preview}{extra}"
    )


async def fetch_document(
    url: str,
    *,
    getter: Getter | None = None,
    timeout: int = 20,
    max_bytes: int = 2_000_000,
    resolve: Any = resolve_host,
) -> tuple[str, str, str, str]:
    status, final_url, headers, content = await _get_public(
        url,
        getter=getter or _httpx_get,
        timeout=timeout,
        max_bytes=max_bytes,
        resolve=resolve,
    )
    if status >= 400:
        raise FetchError(f"HTTP {status}")
    ctype = (headers.get("content-type") or headers.get("Content-Type") or "").split(";", 1)[0].strip()
    if looks_like_pdf(content, ctype):
        try:
            text = pdf_to_text(content)
        except ValueError as exc:
            raise FetchError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise FetchError(f"unable to extract text from PDF: {exc}") from exc
        title = urlparse(final_url).path.rsplit("/", 1)[-1] or final_url
        return final_url, title, text, ctype or "application/pdf"
    if ctype.startswith("image/") or ctype.startswith("audio/") or ctype.startswith("video/"):
        raise FetchError(f"binary content is not extractable ({ctype or 'unknown type'})")
    if looks_like_html(content, ctype) or not ctype or ctype.startswith("text/"):
        raw = content.decode("utf-8", errors="replace")
        if looks_like_html(content, ctype):
            title, text = html_to_text(raw)
            return final_url, title, text, ctype or "text/html"
        return final_url, urlparse(final_url).path.rsplit("/", 1)[-1] or final_url, raw, ctype or "text/plain"
    raise FetchError(f"binary content is not extractable ({ctype or 'unknown type'})")


async def _get_public(
    url: str,
    *,
    getter: Getter,
    timeout: int,
    max_bytes: int,
    resolve: Any,
    max_redirects: int = 5,
) -> tuple[int, str, dict[str, str], bytes]:
    current = url
    for _ in range(max_redirects + 1):
        await _assert_public(current, resolve=resolve)
        reply = await getter(current, timeout=timeout)
        headers = {str(k).lower(): str(v) for k, v in (reply.headers or {}).items()}
        length = headers.get("content-length")
        if length and length.isdigit() and int(length) > max_bytes:
            raise FetchError(f"response larger than {max_bytes} bytes")
        if 300 <= reply.status_code < 400:
            location = headers.get("location")
            if not location:
                raise FetchError("redirect without location")
            current = urljoin(current, location)
            continue
        content = reply.content or b""
        if len(content) > max_bytes:
            raise FetchError(f"response larger than {max_bytes} bytes")
        return reply.status_code, current, headers, content
    raise FetchError("too many redirects")


async def _assert_public(url: str, *, resolve: Any) -> None:
    reason = blocked_reason(url)
    if reason:
        raise FetchError(reason)
    host = urlparse(url).hostname or ""
    if host and not is_ip_literal(host):
        try:
            ips = await resolve(host)
        except OSError as exc:
            raise FetchError(f"could not resolve host: {host}") from exc
        reason = blocked_reason(url, resolved_ips=ips)
        if reason:
            raise FetchError(reason)


# Wikimedia and others reject the default python-httpx UA (HTTP 403) and also
# reject browser spoofing. Identify as a bot with a contact-ish description.
_FETCH_HEADERS = {
    "User-Agent": "DeepResearchAgent/0.1 (local research; +https://github.com/) python-httpx",
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,text/plain;q=0.8,*/*;q=0.7",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


async def _httpx_get(url: str, *, timeout: float) -> HttpReply:
    import httpx

    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, headers=_FETCH_HEADERS
    ) as client:
        resp = await client.get(url)
        return HttpReply(
            status_code=resp.status_code,
            headers={k.lower(): v for k, v in resp.headers.items()},
            content=resp.content,
        )
