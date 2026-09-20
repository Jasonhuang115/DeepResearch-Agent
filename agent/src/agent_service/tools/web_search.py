from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from agent_service.config import settings
from agent_service.sources.ledger import SourceLedger
from agent_service.workspace.protocol import Workspace

DESCRIPTION = "Search the web for sources and evidence related to the research question."
PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search query"},
        "max_results": {"type": "integer", "minimum": 1, "description": "Max results to return"},
    },
    "required": ["query"],
}

TAVILY_URL = "https://api.tavily.com/search"


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    excerpt: str


class Searcher(Protocol):
    provider: str

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]: ...


class SearchError(Exception):
    pass


class MockSearcher:
    provider = "mock"

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        q = query.strip()
        if not q:
            return []
        hits = [
            SearchHit("Mock source A", "https://example.com/mock-a", f"Mock excerpt A for “{q}”."),
            SearchHit("Mock source B", "https://example.com/mock-b", f"Mock excerpt B for “{q}”."),
            SearchHit("Mock source C", "https://example.com/mock-c", f"Mock excerpt C for “{q}”."),
        ]
        return hits[:max_results]


class TavilySearcher:
    provider = "tavily"

    def __init__(self, api_key: str, *, client: Any | None = None) -> None:
        self.api_key = api_key
        self.client = client

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "include_answer": False,
        }
        resp = await _post_tavily(self.client, payload)
        status = int(getattr(resp, "status_code", 0) or 0)
        if status == 429:
            raise SearchError("search quota exceeded")
        if status >= 400:
            raise SearchError(f"search provider HTTP {status}")
        try:
            data = resp.json()
        except Exception as exc:
            raise SearchError(f"search provider returned invalid JSON: {exc}") from exc
        hits: list[SearchHit] = []
        for item in data.get("results") or []:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            title = str(item.get("title") or url).strip()
            excerpt = str(item.get("content") or "").strip()
            hits.append(SearchHit(title=title, url=url, excerpt=excerpt[:500]))
        return hits


def default_searcher() -> Searcher:
    provider = (settings.web_search_provider or "mock").strip().lower()
    if provider == "mock":
        return MockSearcher()
    if provider == "tavily":
        if not settings.tavily_api_key:
            raise SearchError("TAVILY_API_KEY is not set")
        return TavilySearcher(settings.tavily_api_key)
    raise SearchError(f"unknown WEB_SEARCH_PROVIDER: {provider}")


async def web_search(
    workspace: Workspace,
    ledger: SourceLedger,
    args: dict[str, Any],
    *,
    searcher: Searcher | None = None,
) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        return "error: query is required"
    limit = int(args["max_results"]) if args.get("max_results") is not None else settings.web_search_max_results
    limit = max(1, min(limit, 10))
    try:
        engine = searcher or default_searcher()
        hits = await engine.search(query, max_results=limit)
    except SearchError as exc:
        return f"error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"error: search failed: {exc}"
    await ledger.record_query(query, result_count=len(hits), provider=engine.provider)
    if not hits:
        return f"error: no results for {query}"
    lines = [f"provider: {engine.provider}", f"query: {query}", f"results: {len(hits)}", ""]
    if engine.provider == "mock":
        lines.append("These hits are mock placeholders, not evidence. Do not cite them as real pages.")
        lines.append("")
    for hit in hits:
        status = "mock" if engine.provider == "mock" else "ok"
        body = _search_body(hit, query, engine.provider)
        record = await ledger.add(
            url=hit.url,
            title=hit.title,
            excerpt=hit.excerpt,
            status=status,
            query=query,
            provider=engine.provider,
            body=body,
            emit=engine.provider != "mock",
        )
        lines.append(f"{record.source_id}\t{record.title}\t{record.url}")
        if record.excerpt:
            lines.append(record.excerpt)
        lines.append(f"path: {record.path}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _search_body(hit: SearchHit, query: str, provider: str) -> str:
    return (
        f"# {hit.title}\n\n"
        f"URL: {hit.url}\n"
        f"Query: {query}\n"
        f"Provider: {provider}\n\n"
        f"{hit.excerpt}\n"
    )


async def _post_tavily(client: Any | None, payload: dict[str, Any]) -> Any:
    if client is not None:
        return await client.post(TAVILY_URL, json=payload)
    import httpx

    async with httpx.AsyncClient(timeout=20) as http:
        return await http.post(TAVILY_URL, json=payload)
