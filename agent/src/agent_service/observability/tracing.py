from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from agent_service.config import settings
from research_engine.trace import NullSpan, NullTracer, Span

log = logging.getLogger("agent_service.observability")

_FLUSH_TIMEOUT_SEC = 5


@dataclass
class Totals:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    web_search_count: int = 0
    turns: int = 0


_totals: ContextVar[Totals | None] = ContextVar("opik_run_totals", default=None)


def build_tracer() -> NullTracer | OpikTracer:
    """Process-wide tracer. Tests never open a real Opik client."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return NullTracer()
    return make_tracer(settings.opik_api_key)


def make_tracer(api_key: str) -> NullTracer | OpikTracer:
    if not api_key.strip():
        return NullTracer()
    return OpikTracer()


class OpikTracer:
    _ready = False
    _logged = False

    def trace(
        self,
        name: str,
        *,
        thread_id: str = "",
        metadata: dict[str, Any] | None = None,
        **fields: Any,
    ) -> Iterator[Span]:
        return self._trace(name, thread_id=thread_id, metadata=metadata, **fields)

    @contextmanager
    def _trace(
        self,
        name: str,
        *,
        thread_id: str = "",
        metadata: dict[str, Any] | None = None,
        **fields: Any,
    ) -> Iterator[Span]:
        _ = fields
        self.detach_inherited()
        totals = Totals()
        token = _totals.set(totals)
        try:
            if not self._ensure():
                yield NullSpan()
                return
            try:
                import opik

                cm = opik.start_as_current_trace(
                    name,
                    thread_id=thread_id or None,
                    metadata=dict(metadata or {}),
                    project_name=settings.opik_project_name,
                )
                current = cm.__enter__()
            except Exception:
                log.exception("opik trace open failed")
                yield NullSpan()
                return
            handle = _BoundSpan(current)
            try:
                yield handle
            finally:
                try:
                    _stamp(current, totals, handle.fields)
                    cm.__exit__(None, None, None)
                except Exception:
                    log.exception("opik trace close failed")
                self.flush()
        finally:
            _totals.reset(token)

    @contextmanager
    def span(self, name: str, **fields: Any) -> Iterator[Span]:
        if not self._ensure():
            yield NullSpan()
            return
        try:
            import opik

            cm = opik.start_as_current_span(
                name,
                type=_span_type(name),
                project_name=settings.opik_project_name,
                model=fields.get("model") if isinstance(fields.get("model"), str) else None,
            )
            current = cm.__enter__()
        except Exception:
            log.exception("opik span open failed")
            yield NullSpan()
            return
        handle = _BoundSpan(current)
        if fields:
            handle.annotate(**fields)
        try:
            yield handle
        finally:
            try:
                cm.__exit__(None, None, None)
            except Exception:
                log.exception("opik span close failed")

    def add_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        totals = _totals.get()
        if totals is None:
            return
        totals.prompt_tokens += int(prompt_tokens or 0)
        totals.completion_tokens += int(completion_tokens or 0)

    def add_search(self) -> None:
        totals = _totals.get()
        if totals is None:
            return
        totals.web_search_count += 1

    def add_turn(self) -> None:
        totals = _totals.get()
        if totals is None:
            return
        totals.turns += 1

    def current_turns(self) -> int:
        totals = _totals.get()
        return 0 if totals is None else totals.turns

    def detach_inherited(self) -> None:
        try:
            from opik import context_storage

            context_storage.clear_all()
        except Exception:
            log.exception("opik context clear failed")

    def flush(self) -> None:
        if not OpikTracer._ready:
            return
        try:
            import opik

            opik.get_global_client().flush(timeout=_FLUSH_TIMEOUT_SEC)
        except Exception:
            log.exception("opik flush failed")

    def _ensure(self) -> bool:
        if OpikTracer._ready:
            return True
        try:
            import opik
            from opik import config as opik_config

            opik_config.update_session_config("api_key", settings.opik_api_key)
            opik_config.update_session_config("workspace", settings.opik_workspace)
            opik_config.update_session_config("project_name", settings.opik_project_name)
            opik_config.update_session_config("sentry_enable", False)
            if settings.opik_url_override:
                opik_config.update_session_config("url_override", settings.opik_url_override)
            kwargs: dict[str, Any] = {
                "api_key": settings.opik_api_key,
                "workspace": settings.opik_workspace,
                "project_name": settings.opik_project_name,
            }
            if settings.opik_url_override:
                kwargs["host"] = settings.opik_url_override
            opik.set_global_client(opik.Opik(**kwargs))
            OpikTracer._ready = True
            return True
        except Exception:
            if not OpikTracer._logged:
                log.exception("opik tracer disabled")
                OpikTracer._logged = True
            return False


class _BoundSpan:
    def __init__(self, current: Any) -> None:
        self._current = current
        self.fields: dict[str, Any] = {}

    def annotate(self, **fields: Any) -> None:
        self.fields.update(fields)
        try:
            _apply(self._current, fields)
        except Exception:
            log.exception("opik annotate failed")


def _span_type(name: str) -> str:
    if name == "llm":
        return "llm"
    if name.startswith("tool."):
        return "tool"
    return "general"


def _apply(current: Any, fields: dict[str, Any]) -> None:
    meta = dict(getattr(current, "metadata", None) or {})
    output = dict(getattr(current, "output", None) or {})
    for key, value in fields.items():
        if value is None:
            continue
        if key == "usage":
            current.usage = value
        elif key == "model" and isinstance(value, str):
            meta["model"] = value
            if hasattr(current, "model"):
                current.model = value
        elif key == "input" and isinstance(value, dict):
            current.input = value
        elif key == "output" and isinstance(value, dict):
            output.update(value)
        else:
            meta[key] = value
    if meta:
        current.metadata = meta
    if output:
        current.output = output


def _stamp(current: Any, totals: Totals, fields: dict[str, Any]) -> None:
    _apply(current, fields)
    meta = dict(getattr(current, "metadata", None) or {})
    meta["prompt_tokens"] = totals.prompt_tokens
    meta["completion_tokens"] = totals.completion_tokens
    meta["web_search_count"] = totals.web_search_count
    meta["turns"] = totals.turns
    current.metadata = meta
    output = dict(getattr(current, "output", None) or {})
    output["prompt_tokens"] = totals.prompt_tokens
    output["completion_tokens"] = totals.completion_tokens
    output["web_search_count"] = totals.web_search_count
    output["turns"] = totals.turns
    if "status" in fields and fields["status"] is not None:
        output["status"] = fields["status"]
    current.output = output
