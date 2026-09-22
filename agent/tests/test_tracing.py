from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from agent_service.config import settings
from agent_service.envfile import load_repo_env
from agent_service.observability.tracing import OpikTracer, build_tracer, make_tracer
from research_engine.llm.scripted import ScriptedLLM
from research_engine.loop import run_loop
from research_engine.trace import NullTracer, tool_input
from research_engine.types import TokenUsage, ToolCall, TurnResult


class RecordingSeq:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, typ: str, payload: dict | None = None) -> None:
        self.events.append((typ, payload or {}))


class _Span:
    def __init__(self, store: dict[str, Any]) -> None:
        self._store = store

    def annotate(self, **fields: Any) -> None:
        self._store.update(fields)


class RecordingTracer:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.annotations: list[tuple[str, dict[str, Any]]] = []
        self.usage: list[tuple[int, int]] = []
        self.searches = 0

    def trace(self, name: str, **_fields: Any) -> Iterator[_Span]:
        return self.span(name)

    @contextmanager
    def span(self, name: str, **_fields: Any) -> Iterator[_Span]:
        self.events.append(("open", name))
        store: dict[str, Any] = {}
        try:
            yield _Span(store)
        finally:
            self.annotations.append((name, store))
            self.events.append(("close", name))

    def add_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.usage.append((prompt_tokens, completion_tokens))

    def add_search(self) -> None:
        self.searches += 1

    def add_turn(self) -> None:
        return None

    def current_turns(self) -> int:
        return sum(1 for kind, name in self.events if kind == "open" and name == "turn")

    def flush(self) -> None:
        return None


class _Tools:
    def __init__(self, fn) -> None:
        self._fn = fn

    def get(self, name: str):
        if name == "web_search":
            return self._fn
        return None

    def openai_tools(self) -> list[dict[str, Any]]:
        return []


def _balanced(events: list[tuple[str, str]]) -> None:
    depth = 0
    for kind, _name in events:
        depth += 1 if kind == "open" else -1
        assert depth >= 0
    assert depth == 0


def _call(query: str) -> ToolCall:
    return ToolCall(id="c1", name="web_search", arguments=f'{{"query":"{query}"}}')


async def _search(_args: dict[str, Any]) -> str:
    return "a long page body that must stay out of the trace"


@pytest.mark.asyncio
async def test_span_order_is_turn_llm_tool() -> None:
    tracer = RecordingTracer()
    llm = ScriptedLLM(
        [
            TurnResult(content="search", tool_calls=[_call("solid")], usage=TokenUsage(3, 4)),
            TurnResult(content="done", usage=TokenUsage(5, 6)),
        ]
    )
    seq = RecordingSeq()
    await run_loop(
        llm=llm,
        tools=_Tools(_search),
        messages=[{"role": "user", "content": "q"}],
        seq=seq,
        cancel=asyncio.Event(),
        max_turns=4,
        max_report_chars=1000,
        tracer=tracer,
    )
    assert tracer.events == [
        ("open", "turn"),
        ("open", "llm"),
        ("close", "llm"),
        ("open", "tool.web_search"),
        ("close", "tool.web_search"),
        ("close", "turn"),
        ("open", "turn"),
        ("open", "llm"),
        ("close", "llm"),
        ("close", "turn"),
    ]
    llm_ann = next(fields for name, fields in tracer.annotations if name == "llm")
    assert llm_ann["usage"]["prompt_tokens"] == 3
    assert llm_ann["tool_names"] == ["web_search"]
    assert "content" not in llm_ann
    tool_ann = next(fields for name, fields in tracer.annotations if name == "tool.web_search")
    assert tool_ann["input"] == {"query": "solid"}
    assert tool_ann["ok"] is True
    assert "a long page body" not in str(tool_ann)
    assert tracer.usage == [(3, 4), (5, 6)]
    assert tracer.searches == 1
    assert seq.events[-1][1]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_cancel_and_failure_close_spans() -> None:
    cancel = asyncio.Event()

    async def stop(_args: dict[str, Any]) -> str:
        cancel.set()
        return "partial"

    tracer = RecordingTracer()
    await run_loop(
        llm=ScriptedLLM([TurnResult(content="go", tool_calls=[_call("q")])]),
        tools=_Tools(stop),
        messages=[{"role": "user", "content": "q"}],
        seq=RecordingSeq(),
        cancel=cancel,
        max_turns=4,
        max_report_chars=1000,
        tracer=tracer,
    )
    _balanced(tracer.events)
    assert ("close", "tool.web_search") in tracer.events
    assert ("close", "turn") in tracer.events

    class Boom:
        model = "scripted"

        async def complete(self, *_args: Any, **_kwargs: Any) -> TurnResult:
            raise RuntimeError("llm down")

    failed = RecordingTracer()
    seq = RecordingSeq()
    await run_loop(
        llm=Boom(),
        tools=_Tools(_search),
        messages=[{"role": "user", "content": "q"}],
        seq=seq,
        cancel=asyncio.Event(),
        max_turns=2,
        max_report_chars=1000,
        tracer=failed,
    )
    _balanced(failed.events)
    assert ("close", "llm") in failed.events
    assert seq.events[-1][1]["status"] == "failed"


def test_empty_key_is_noop_and_does_not_report(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(make_tracer(""), NullTracer)
    assert isinstance(make_tracer("  "), NullTracer)
    monkeypatch.setattr(settings, "opik_api_key", "secret")
    assert isinstance(build_tracer(), NullTracer)

    tracer = OpikTracer()
    monkeypatch.setattr(tracer, "_ensure", lambda: False)
    monkeypatch.setattr(tracer, "detach_inherited", lambda: None)
    with tracer.trace("run", thread_id="conv", metadata={"run_id": "r"}) as span:
        with tracer.span("llm") as inner:
            inner.annotate(model="m", usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})
        span.annotate(status="succeeded")
    tracer.add_usage(1, 2)
    tracer.flush()


def test_opik_trace_stamps_totals_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: dict[str, Any] = {}

    class _Obj:
        def __init__(self) -> None:
            self.metadata: dict[str, Any] | None = None
            self.output: dict[str, Any] | None = None
            self.input = None
            self.usage = None
            self.model = None

    class _CM:
        def __init__(self, obj: _Obj) -> None:
            self._obj = obj

        def __enter__(self) -> _Obj:
            return self._obj

        def __exit__(self, *_args: Any) -> bool:
            return False

    def start_trace(name: str, **kwargs: Any) -> _CM:
        obj = _Obj()
        obj.metadata = dict(kwargs.get("metadata") or {})
        opened["trace"] = obj
        opened["trace_name"] = name
        opened["trace_kwargs"] = kwargs
        return _CM(obj)

    def start_span(name: str, **kwargs: Any) -> _CM:
        obj = _Obj()
        opened.setdefault("spans", []).append((name, kwargs, obj))
        return _CM(obj)

    fake = types.ModuleType("opik")
    fake.start_as_current_trace = start_trace
    fake.start_as_current_span = start_span
    monkeypatch.setitem(sys.modules, "opik", fake)

    tracer = OpikTracer()
    monkeypatch.setattr(tracer, "_ensure", lambda: True)
    monkeypatch.setattr(tracer, "detach_inherited", lambda: None)
    monkeypatch.setattr(tracer, "flush", lambda: None)
    with tracer.trace("run", thread_id="conv", metadata={"run_id": "r"}) as span:
        tracer.add_usage(3, 4)
        tracer.add_search()
        tracer.add_turn()
        with tracer.span("llm") as inner:
            inner.annotate(
                model="deepseek-flash",
                finish_reason="stop",
                message_count=2,
                output_chars=4,
                tool_names=["web_search"],
                usage={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            )
        with tracer.span("tool.web_search") as tool:
            tool.annotate(ok=True, result_chars=10, overflowed=False, input={"query": "solid"})
        span.annotate(status="succeeded", model="deepseek-flash")

    trace = opened["trace"]
    assert opened["trace_name"] == "run"
    assert opened["trace_kwargs"]["thread_id"] == "conv"
    assert opened["trace_kwargs"]["project_name"] == settings.opik_project_name
    assert trace.output["status"] == "succeeded"
    assert trace.output["prompt_tokens"] == 3
    assert trace.output["completion_tokens"] == 4
    assert trace.output["web_search_count"] == 1
    assert trace.metadata["turns"] == 1
    assert trace.metadata["model"] == "deepseek-flash"
    span_names = [name for name, _kwargs, _obj in opened["spans"]]
    assert span_names == ["llm", "tool.web_search"]
    assert opened["spans"][0][1]["type"] == "llm"
    assert opened["spans"][1][1]["type"] == "tool"
    llm_obj = opened["spans"][0][2]
    assert llm_obj.model == "deepseek-flash"
    assert llm_obj.usage["total_tokens"] == 7
    assert llm_obj.metadata["message_count"] == 2
    assert "content" not in llm_obj.metadata
    assert opened["spans"][1][2].input == {"query": "solid"}


def test_tool_input_omits_file_bodies() -> None:
    assert tool_input("Write", {"path": "a.md", "content": "secret pdf text"}) == {"path": "a.md"}
    assert tool_input("web_fetch", {"url": "https://example.com/a"}) == {"url": "https://example.com/a"}
    assert "secret" not in str(tool_input("Bash", {"command": "echo hi", "timeout_sec": 1}))


def test_env_file_does_not_override(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("OPIK_API_KEY", "already")
    monkeypatch.delenv("Opik_key", raising=False)
    monkeypatch.delenv("OPIK_PROJECT_NAME", raising=False)
    path = tmp_path / ".env"
    path.write_text(
        '\n'.join(
            [
                "Opik_key=from-file",
                "OPIK_API_KEY=other",
                "# comment",
                'export OPIK_PROJECT_NAME="deep-research"',
            ]
        ),
        encoding="utf-8",
    )
    load_repo_env(path)
    assert os.environ["OPIK_API_KEY"] == "already"
    assert os.environ["Opik_key"] == "from-file"
    assert os.environ["OPIK_PROJECT_NAME"] == "deep-research"


def test_settings_read_opik_key_before_import(tmp_path) -> None:
    path = tmp_path / ".env"
    path.write_text("Opik_key=from-file\n", encoding="utf-8")
    code = (
        "import os\n"
        "from pathlib import Path\n"
        "os.environ.pop('OPIK_API_KEY', None)\n"
        "os.environ.pop('Opik_key', None)\n"
        "os.environ.pop('OPIK_WORKSPACE', None)\n"
        "os.environ.pop('OPIK_PROJECT_NAME', None)\n"
        "from agent_service.envfile import load_repo_env\n"
        f"load_repo_env(Path({str(path)!r}))\n"
        "from agent_service.config import settings\n"
        "print(settings.opik_api_key)\n"
        "print(settings.opik_workspace)\n"
        "print(settings.opik_project_name)\n"
    )
    env = os.environ.copy()
    env.pop("OPIK_API_KEY", None)
    env.pop("Opik_key", None)
    env.pop("OPIK_WORKSPACE", None)
    env.pop("OPIK_PROJECT_NAME", None)
    env["PYTHONPATH"] = "src"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == ["from-file", "jasonhuang115", "deep-research"]
