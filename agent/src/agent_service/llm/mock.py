from __future__ import annotations


class MockLLM:
    async def complete(self, prompt: str) -> str:
        return f"(mock) considered: {prompt[:80]}"
