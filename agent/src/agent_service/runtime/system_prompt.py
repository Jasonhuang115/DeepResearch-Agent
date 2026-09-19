"""Assemble the system prompt from numbered markdown fragments.

Filenames ``NN-foo.md`` become XML tags ``<foo>``. Dynamic context and
language sit in a trailing ``<system-reminder>`` block, matching the
pharmmaster layout without skills or chemistry discipline.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

_CJK = re.compile(r"[\u3400-\u9fff]")


@dataclass
class PromptFragment:
    name: str
    body: str

    @property
    def section_name(self) -> str:
        stem = self.name
        if len(stem) >= 3 and stem[:2].isdigit() and stem[2] == "-":
            stem = stem[3:]
        return stem.replace("-", "_")


def _load_prompt_fragments() -> list[PromptFragment]:
    fragments: list[PromptFragment] = []
    pkg = resources.files("agent_service.prompts")
    for entry in sorted(pkg.iterdir(), key=lambda p: p.name):
        if not entry.name.endswith(".md"):
            continue
        stem = Path(entry.name).stem
        fragments.append(PromptFragment(name=stem, body=entry.read_text(encoding="utf-8")))
    return fragments


_BASE_FRAGMENTS: list[PromptFragment] = _load_prompt_fragments()


def detect_reply_language(text: str) -> str:
    if _CJK.search(text or ""):
        return "Chinese"
    return "English"


def build_system_prompt(
    *,
    conversation_id: str = "",
    run_id: str = "",
    reply_language: str | None = None,
) -> str:
    sections: list[str] = []
    for fragment in _BASE_FRAGMENTS:
        tag = fragment.section_name
        sections.append(f"<{tag}>\n{fragment.body.strip()}\n</{tag}>")
        sections.append("")

    sections.append("<system-reminder>")
    sections.append("")
    context_payload: dict[str, Any] = {
        "conversation_id": conversation_id,
        "run_id": run_id,
    }
    sections.append("<context>")
    sections.append(json.dumps(context_payload, ensure_ascii=False, indent=2))
    sections.append("</context>")
    sections.append("")
    if reply_language:
        sections.append(_language_directive(reply_language))
        sections.append("")
    sections.append("</system-reminder>")
    return "\n".join(sections)


def _language_directive(language: str) -> str:
    return (
        "<language>\n"
        f"The user's latest message is in {language}. Write your ENTIRE "
        f"reply — every sentence, heading, table cell and list item — in {language}.\n"
        "Keep Latin-script domain identifiers verbatim.\n"
        "</language>"
    )


def load_prompt_fragments() -> list[PromptFragment]:
    return _load_prompt_fragments()
