from __future__ import annotations

from research_engine.types import EventEmitter

BOUNDARY_OVERLAP_WINDOW = 2_048
MIN_BOUNDARY_OVERLAP = 16
MAX_TRUNCATED_TOOL_CALL_REGENERATIONS = 2
CONTINUATION_PROMPT = (
    "Continue exactly where the previous response was cut off. Do not restart, "
    "repeat headings, summarize earlier content, or mention the interruption. "
    "Return only the missing continuation and finish the answer."
)


def boundary_overlap(previous: str, following: str) -> int:
    """Bounded exact suffix/prefix overlap, safe to remove once."""
    limit = min(len(previous), len(following), BOUNDARY_OVERLAP_WINDOW)
    for size in range(limit, MIN_BOUNDARY_OVERLAP - 1, -1):
        if previous[-size:] == following[:size]:
            return size
    return 0


def visible_text(content: str, overlap: int) -> str:
    if overlap <= 0:
        return content
    if overlap >= len(content):
        return ""
    return content[overlap:]


class LiveDeltas:
    """Forward segment text as it arrives."""

    def __init__(self, seq: EventEmitter) -> None:
        self._seq = seq
        self.emitted = False
        self.saw_input = False

    async def emit(self, piece: str) -> None:
        if not piece:
            return
        self.saw_input = True
        self.emitted = True
        await self._seq.emit("text_delta", {"delta": piece})

    async def finish(self) -> int:
        return 0


class ContinuationDeltas:
    """Hold a bounded prefix, drop one suffix/prefix overlap, then stream the rest."""

    def __init__(self, seq: EventEmitter, previous: str) -> None:
        self._seq = seq
        self._previous = previous
        self._buffer: list[str] = []
        self._size = 0
        self._flushed = False
        self.overlap = 0
        self.emitted = False
        self.saw_input = False

    async def emit(self, piece: str) -> None:
        if not piece:
            return
        self.saw_input = True
        if self._flushed:
            self.emitted = True
            await self._seq.emit("text_delta", {"delta": piece})
            return
        self._buffer.append(piece)
        self._size += len(piece)
        if self._size >= BOUNDARY_OVERLAP_WINDOW:
            await self._flush()

    async def finish(self) -> int:
        await self._flush()
        return self.overlap

    async def _flush(self) -> None:
        if self._flushed:
            return
        prefix = "".join(self._buffer)
        self.overlap = boundary_overlap(self._previous, prefix)
        visible = prefix[self.overlap :]
        if visible:
            self.emitted = True
            await self._seq.emit("text_delta", {"delta": visible})
        self._flushed = True
