from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.tools.overflow import Overflow
from agent_service.workspace.local import LocalProvider
from research_engine.types import ToolCall


def _call(name: str, cid: str = "tc_1") -> ToolCall:
    return ToolCall(id=cid, name=name, arguments="{}")


@pytest.mark.asyncio
async def test_overflow_writes_full_and_returns_head_tail(tmp_path: Path) -> None:
    ws = await LocalProvider(tmp_path).ensure("conv")
    overflow = Overflow(ws, run_id="run_1", max_chars=100)
    body = "HEADDATA\n" + ("m" * 8000) + "\nTAILDATA\n"
    out = await overflow.apply(_call("Bash"), body)
    saved = await ws.read_text("tool-output/run_1/tc_1.txt")
    assert saved == body
    assert "HEADDATA" in out
    assert "TAILDATA" in out
    assert "tool-output/run_1/tc_1.txt" in out
    assert "m" * 5000 not in out
    index = await ws.read_text("sources/index.json")
    assert "tc_1" in index
    assert "tool-output/run_1/tc_1.txt" in index


@pytest.mark.asyncio
async def test_overflow_without_workspace_does_not_invent_path() -> None:
    overflow = Overflow(None, run_id="run_1", max_chars=50)
    body = "x" * 200
    out = await overflow.apply(_call("Read"), body)
    assert "tool-output/" not in out
    assert "truncated" in out
    assert out.startswith("x" * 50) or "x" * 40 in out


@pytest.mark.asyncio
async def test_overflow_always_store_keeps_short_body(tmp_path: Path) -> None:
    ws = await LocalProvider(tmp_path).ensure("conv")
    overflow = Overflow(ws, run_id="child", max_chars=100, always_store=True)
    out = await overflow.apply(_call("Read", "c3"), "SHORT_BODY")
    assert out == "SHORT_BODY"
    assert await ws.read_text("tool-output/child/c3.txt") == "SHORT_BODY"


@pytest.mark.asyncio
async def test_overflow_skips_web_tools(tmp_path: Path) -> None:
    ws = await LocalProvider(tmp_path).ensure("conv")
    overflow = Overflow(ws, run_id="run_1", max_chars=10)
    huge = "y" * 500
    out = await overflow.apply(_call("web_fetch", "c2"), huge)
    assert out == huge
    names = await ws.list_files("tool-output/**")
    assert names == []


@pytest.mark.asyncio
async def test_registry_after_result_spills(tmp_path: Path) -> None:
    from agent_service.tools.registry import ToolRegistry

    ws = await LocalProvider(tmp_path).ensure("conv")
    registry = ToolRegistry()
    registry.overflow = Overflow(ws, run_id="run_z", max_chars=30)

    async def big(_args: dict) -> str:
        return "Q" * 200

    registry.register("Bash", big, description="bash", parameters={"type": "object", "properties": {}})
    out = await registry.after_result(_call("Bash", "id9"), await registry.get("Bash")({}))
    assert "tool-output/run_z/id9.txt" in out
    assert await ws.read_text("tool-output/run_z/id9.txt") == "Q" * 200
