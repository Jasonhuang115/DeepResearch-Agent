from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from agent_service.sources.catalog import IndexEntry, load_index, render_catalog_chapter
from agent_service.workspace.protocol import Workspace
from research_engine.types import EventEmitter, LLMClient, TurnResult

log = logging.getLogger("agent_service.context")

_SRC_ID = re.compile(r"\bsrc_\d+\b")
_CJK_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x3040, 0x30FF),
    (0xAC00, 0xD7AF),
)

SUMMARY_RESERVE = 1600
COMPACT_PROMPT = """You summarize a research session so the agent does not drift after old tool turns are dropped.

Write EXACTLY these headings and nothing else (no 工具正文 chapter):

## Goal
## Done
## Continue
未决：
焦点：
矛盾：

Rules:
- Goal: the aligned research goal after discussion. Copy brief.md if it was provided. Unstated constraints (scope, year, source type) as「未声明」. Do not expand the user's question into a broader survey.
- Done: completed subtasks, one line each, like「已定位 2024 年报并抽毛利率口径」. No specific numbers, quotes, or excerpts.
- Continue.未决: unanswered questions that still belong to Goal.
- Continue.焦点: exactly one current focus from 未决.
- Continue.矛盾: only which sources disagree (e.g. src_03 与 src_07 对不上), or「无」. No synthesized numbers.
- Cite only these ids: {source_ids}
- Do not invent source ids. Do not list searches to run next. Do not paste tool output.
"""


def estimate_tokens(text: str) -> int:
    tokens = 0
    buf = 0
    for ch in text:
        if _is_cjk(ch):
            if buf:
                tokens += (buf + 3) // 4
                buf = 0
            tokens += 1
        else:
            buf += 1
    if buf:
        tokens += (buf + 3) // 4
    return tokens


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in _CJK_RANGES)


def message_tokens(message: dict[str, Any]) -> int:
    n = estimate_tokens(str(message.get("role") or ""))
    n += estimate_tokens(str(message.get("content") or ""))
    n += estimate_tokens(str(message.get("tool_call_id") or ""))
    calls = message.get("tool_calls")
    if calls:
        n += estimate_tokens(json.dumps(calls, ensure_ascii=False))
    return n + 4


def window_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(message_tokens(m) for m in messages)


def split_pair_blocks(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
    """Keep leading system messages; group assistant.tool_calls with following role=tool."""
    i = 0
    system: list[dict[str, Any]] = []
    while i < len(messages) and messages[i].get("role") == "system":
        system.append(messages[i])
        i += 1
    blocks: list[list[dict[str, Any]]] = []
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            group = [msg]
            i += 1
            while i < len(messages) and messages[i].get("role") == "tool":
                group.append(messages[i])
                i += 1
            blocks.append(group)
            continue
        if msg.get("role") == "tool":
            if blocks and blocks[-1] and blocks[-1][0].get("role") == "assistant" and blocks[-1][0].get("tool_calls"):
                blocks[-1].append(msg)
            else:
                blocks.append([msg])
            i += 1
            continue
        blocks.append([msg])
        i += 1
    return system, blocks


def plan_compact(
    system: list[dict[str, Any]],
    blocks: list[list[dict[str, Any]]],
    budget: int,
    *,
    reserve: int = SUMMARY_RESERVE,
) -> tuple[list[list[dict[str, Any]]], list[list[dict[str, Any]]]] | None:
    sys_tok = sum(message_tokens(m) for m in system)
    block_toks = [sum(message_tokens(m) for m in block) for block in blocks]
    if sys_tok + sum(block_toks) <= budget:
        return None
    kept: list[list[dict[str, Any]]] = []
    used = sys_tok + reserve
    for block, cost in zip(reversed(blocks), reversed(block_toks)):
        if kept and used + cost > budget:
            break
        kept.append(block)
        used += cost
    kept.reverse()
    drop = len(blocks) - len(kept)
    if drop <= 0:
        return None
    return blocks[:drop], kept


@dataclass
class ContextPacker:
    llm: LLMClient | None = None
    workspace: Workspace | None = None
    seq: EventEmitter | None = None
    budget: int = 100_000

    async def __call__(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        system, blocks = split_pair_blocks(messages)
        plan = plan_compact(system, blocks, self.budget)
        if plan is None:
            return list(messages)
        dropped, kept = plan
        material = [m for block in dropped for m in block]
        catalog = await self._catalog()
        allowed = {e.id for e in catalog}
        try:
            llm_text = await self._summarize(material, allowed)
        except Exception:
            log.exception("compact llm failed; leaving window unchanged")
            return list(messages)
        summary = _assemble_summary(llm_text, catalog, allowed)
        await self._write_memory(summary)
        out = list(system)
        out.append({"role": "user", "content": f"<summary>\n{summary}\n</summary>"})
        for block in kept:
            out.extend(block)
        if self.seq is not None:
            await self.seq.emit(
                "context.compacted",
                {
                    "dropped_messages": sum(len(b) for b in dropped),
                    "kept_messages": len(out),
                    "tokens_before": window_tokens(messages),
                    "tokens_after": window_tokens(out),
                },
            )
        messages[:] = out
        return messages

    async def _catalog(self) -> list[IndexEntry]:
        if self.workspace is None:
            return []
        try:
            return await load_index(self.workspace)
        except Exception:
            return []

    async def _summarize(self, material: list[dict[str, Any]], allowed: set[str]) -> str:
        if self.llm is None:
            return _fallback_summary(material)
        brief = await self._brief()
        ids = ", ".join(sorted(allowed)) if allowed else "(none)"
        user = COMPACT_PROMPT.format(source_ids=ids)
        if brief:
            user += f"\n\nbrief.md:\n{brief[:2000]}"
        user += "\n\nTranscript to compress:\n" + _material_text(material)
        result: TurnResult = await self.llm.complete(
            [{"role": "user", "content": user}],
            [],
            tool_choice="none",
        )
        text = (result.content or "").strip()
        return text or _fallback_summary(material)

    async def _brief(self) -> str:
        if self.workspace is None:
            return ""
        try:
            return (await self.workspace.read_text("brief.md")).strip()
        except FileNotFoundError:
            return ""
        except Exception:
            return ""

    async def _write_memory(self, summary: str) -> None:
        if self.workspace is None:
            return
        goal, done, continue_part = _split_chapters(summary)
        try:
            await self.workspace.write_text("memory/findings.md", (done or goal).strip() + "\n")
            await self.workspace.write_text("memory/open-questions.md", (continue_part or "").strip() + "\n")
        except Exception:
            log.warning("failed to write memory files after compact")


async def prepare_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list(messages)


def pack_messages(messages: list[dict]) -> list[dict]:
    return list(messages)


def _assemble_summary(llm_text: str, catalog: list[IndexEntry], allowed: set[str]) -> str:
    goal, done, continue_part = _split_chapters(llm_text)
    goal = _filter_ids(goal or "未声明", allowed)
    done = _filter_ids(done or "- （尚无完成项）", allowed)
    continue_part = _filter_ids(continue_part or "未决：未声明\n焦点：未声明\n矛盾：无", allowed)
    catalog_ch = render_catalog_chapter(catalog)
    return "\n\n".join(
        [
            "## Goal\n" + goal.strip(),
            "## Done\n" + done.strip(),
            catalog_ch,
            "## Continue\n" + continue_part.strip(),
        ]
    )


def _split_chapters(text: str) -> tuple[str, str, str]:
    stripped = _strip_tool_chapter(text or "")
    parts = {"goal": "", "done": "", "continue": ""}
    current = None
    for line in stripped.splitlines():
        heading = line.strip().lower().lstrip("#").strip()
        if heading == "goal":
            current = "goal"
            continue
        if heading == "done":
            current = "done"
            continue
        if heading == "continue":
            current = "continue"
            continue
        if current:
            parts[current] += line + "\n"
    return parts["goal"].strip(), parts["done"].strip(), parts["continue"].strip()


def _strip_tool_chapter(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        heading = line.strip().lower().lstrip("#").strip()
        if heading in {"工具正文", "tool bodies", "tool catalog"}:
            skipping = True
            continue
        if skipping and line.startswith("## "):
            skipping = False
        if not skipping:
            out.append(line)
    return "\n".join(out)


def _filter_ids(text: str, allowed: set[str]) -> str:
    if not text:
        return text

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        return token if token in allowed else "未知来源"

    return _SRC_ID.sub(repl, text)


def _material_text(messages: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for msg in messages:
        role = msg.get("role") or ""
        content = str(msg.get("content") or "")
        if role == "tool":
            chunks.append(f"[tool {msg.get('tool_call_id') or ''}]\n{content[:1500]}")
        elif msg.get("tool_calls"):
            names = ",".join(
                str((c.get("function") or {}).get("name") or "") for c in msg.get("tool_calls") or []
            )
            chunks.append(f"[assistant tools={names}]\n{content[:800]}")
        else:
            chunks.append(f"[{role}]\n{content[:2000]}")
    return "\n\n".join(chunks)[:24000]


def _fallback_summary(material: list[dict[str, Any]]) -> str:
    last_user = ""
    for msg in reversed(material):
        if msg.get("role") == "user":
            last_user = str(msg.get("content") or "").strip()
            break
    goal = last_user.split("\n", 1)[0][:200] if last_user else "未声明"
    return f"## Goal\n{goal}\n\n## Done\n- （压缩器回退，细节见工具正文）\n\n## Continue\n未决：未声明\n焦点：未声明\n矛盾：无"
