from __future__ import annotations

from pathlib import Path

import pytest

from agent_service.context.compact import (
    ContextPacker,
    estimate_tokens,
    plan_compact,
    split_pair_blocks,
)
from agent_service.sources.catalog import IndexEntry, save_index
from agent_service.workspace.local import LocalProvider
from research_engine.llm.scripted import ScriptedLLM
from research_engine.types import TurnResult


def _asst_tools(cid: str, name: str = "Bash") -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": "{}"}}],
    }


def test_estimate_tokens_cjk_and_ascii() -> None:
    assert estimate_tokens("毛利率") == 3
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 8) == 2


def test_split_keeps_continuation_with_partial() -> None:
    from research_engine.continuation import CONTINUATION_PROMPT

    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "partial report"},
        {"role": "user", "content": CONTINUATION_PROMPT},
    ]
    _system, blocks = split_pair_blocks(messages)
    assert blocks[-1] == [
        {"role": "assistant", "content": "partial report"},
        {"role": "user", "content": CONTINUATION_PROMPT},
    ]


def test_split_keeps_tool_pairs_together() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
        _asst_tools("c1"),
        {"role": "tool", "tool_call_id": "c1", "content": "out"},
        {"role": "assistant", "content": "done"},
    ]
    system, blocks = split_pair_blocks(messages)
    assert system == [messages[0]]
    assert blocks[1][0]["role"] == "assistant"
    assert blocks[1][1]["role"] == "tool"
    assert len(blocks[1]) == 2


def test_plan_compact_drops_whole_tool_block() -> None:
    system = [{"role": "system", "content": "s"}]
    tool_block = [_asst_tools("c1"), {"role": "tool", "tool_call_id": "c1", "content": "字" * 4000}]
    tail = [[{"role": "user", "content": "continue"}]]
    plan = plan_compact(system, [tool_block, tail[0]], budget=1800, reserve=200)
    assert plan is not None
    dropped, kept = plan
    assert dropped == [tool_block]
    assert kept == tail
    flat = [m for b in kept for m in b]
    assert all(m.get("role") != "tool" for m in flat)


@pytest.mark.asyncio
async def test_compact_inserts_catalog_not_excerpts(tmp_path: Path) -> None:
    ws = await LocalProvider(tmp_path).ensure("conv")
    await save_index(
        ws,
        [
            IndexEntry(id="src_03", tool="web_fetch", title="2024年年报", path="sources/src_03.md"),
            IndexEntry(id="src_07", tool="web_fetch", title="某新闻", path="sources/src_07.md"),
        ],
    )
    await ws.write_text("sources/src_03.md", "毛利率 42.1% secret-excerpt")
    llm = ScriptedLLM(
        [
            TurnResult(
                content=(
                    "## Goal\n宁德时代 2024 年毛利率（对标：未声明）。\n"
                    "## Done\n- [x] 年报已抓到（src_03）\n"
                    "## 工具正文\nshould not appear as excerpt 42.1%\n"
                    "## Continue\n未决：口径\n焦点：核对 src_03 与 src_07\n矛盾：src_03 与 src_99 对不上\n"
                )
            )
        ]
    )
    seq: list[tuple[str, dict]] = []

    class Rec:
        async def emit(self, typ: str, payload=None) -> None:
            seq.append((typ, payload or {}))

    packer = ContextPacker(llm=llm, workspace=ws, seq=Rec(), budget=800)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "研究宁德时代毛利率"},
        _asst_tools("c1", "web_fetch"),
        {"role": "tool", "tool_call_id": "c1", "content": "字" * 3000},
        {"role": "user", "content": "继续"},
    ]
    out = await packer(messages)
    assert out[0]["role"] == "system"
    assert out[1]["role"] == "user"
    assert "<summary>" in out[1]["content"]
    text = out[1]["content"]
    assert "## 工具正文" in text
    assert "src_03" in text
    assert "sources/src_03.md" in text
    assert "secret-excerpt" not in text
    assert "42.1%" not in text
    assert "未知来源" in text
    assert "src_99" not in text
    assert all(m.get("role") != "tool" for m in out)
    assert seq[0][0] == "context.compacted"
    findings = await ws.read_text("memory/findings.md")
    assert "年报已抓到" in findings
    openq = await ws.read_text("memory/open-questions.md")
    assert "口径" in openq
    assert "<summary>" in messages[1]["content"]
