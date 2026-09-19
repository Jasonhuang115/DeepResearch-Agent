from __future__ import annotations

import asyncio
from typing import Any

DESCRIPTION = "Search the web for sources and evidence related to the research question."

PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query",
        },
    },
    "required": ["query"],
}


async def web_search(args: dict[str, Any]) -> str:
    q = str(args.get("query") or "")
    await asyncio.sleep(0.15)
    return (
        f"Mock search results for “{q}”: "
        "source A notes a 2024–2026 shift toward sulfide electrolytes; "
        "source B highlights oxide stability; source C flags scale-up cost."
    )
