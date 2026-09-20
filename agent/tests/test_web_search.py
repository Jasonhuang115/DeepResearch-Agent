from pathlib import Path

import pytest

from agent_service.config import settings
from agent_service.sources.ledger import LEDGER_PATH, SourceLedger
from agent_service.tools.web_search import MockSearcher, SearchError, TavilySearcher, default_searcher, web_search
from agent_service.workspace.local import LocalProvider


class FakeTavily:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.calls: list[tuple[str, dict]] = []

    async def post(self, url: str, json: dict | None = None) -> object:
        self.calls.append((url, json or {}))

        class Reply:
            def __init__(self, status: int, payload: dict) -> None:
                self.status_code = status
                self._payload = payload

            def json(self) -> dict:
                return self._payload

        return Reply(self.status, self.payload)


@pytest.fixture
async def ledger(tmp_path: Path) -> SourceLedger:
    ws = await LocalProvider(tmp_path).ensure("conv")
    return SourceLedger(ws)


@pytest.mark.asyncio
async def test_mock_search_writes_ledger_without_source_event(ledger: SourceLedger) -> None:
    events: list[tuple[str, dict]] = []

    class Seq:
        async def emit(self, typ: str, payload: dict | None = None) -> None:
            events.append((typ, payload or {}))

    ledger.seq = Seq()
    text = await web_search(ledger.workspace, ledger, {"query": "solid-state"}, searcher=MockSearcher())
    assert "src_01" in text
    assert "not evidence" in text
    assert "https://example.com/mock-a" in text
    data = await ledger.load()
    assert data["queries"][0]["query"] == "solid-state"
    assert data["queries"][0]["result_count"] == 3
    assert data["sources"][0]["status"] == "mock"
    assert events == []
    body = await ledger.workspace.read_text("sources/src_01.md")
    assert "Mock excerpt A" in body


@pytest.mark.asyncio
async def test_tavily_search_emits_source_added(ledger: SourceLedger) -> None:
    events: list[tuple[str, dict]] = []

    class Seq:
        async def emit(self, typ: str, payload: dict | None = None) -> None:
            events.append((typ, payload or {}))

    ledger.seq = Seq()
    client = FakeTavily(
        {
            "results": [
                {"title": "CATL", "url": "https://example.com/catl", "content": "battery note"},
                {"title": "No url"},
            ]
        }
    )
    text = await web_search(
        ledger.workspace,
        ledger,
        {"query": "CATL", "max_results": 5},
        searcher=TavilySearcher("tvly-test", client=client),
    )
    assert "src_01" in text
    assert "not evidence" not in text
    assert client.calls[0][1]["query"] == "CATL"
    assert events == [("source.added", {"source_id": "src_01", "url": "https://example.com/catl", "title": "CATL"})]


@pytest.mark.asyncio
async def test_tavily_errors(ledger: SourceLedger) -> None:
    empty = FakeTavily({"results": []})
    text = await web_search(
        ledger.workspace, ledger, {"query": "nothing"}, searcher=TavilySearcher("k", client=empty)
    )
    assert text.startswith("error: no results")
    quota = FakeTavily({}, status=429)
    text = await web_search(
        ledger.workspace, ledger, {"query": "q"}, searcher=TavilySearcher("k", client=quota)
    )
    assert "quota" in text


@pytest.mark.asyncio
async def test_missing_query(ledger: SourceLedger) -> None:
    assert "query is required" in await web_search(ledger.workspace, ledger, {})


def test_default_searcher_tavily_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "web_search_provider", "tavily")
    monkeypatch.setattr(settings, "tavily_api_key", "")
    with pytest.raises(SearchError, match="TAVILY_API_KEY"):
        default_searcher()


def test_default_searcher_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "web_search_provider", "mock")
    assert isinstance(default_searcher(), MockSearcher)
