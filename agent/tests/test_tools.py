import pytest

from agent_service.tools.bash import BASH_NOT_IMPLEMENTED, bash
from agent_service.tools.fs import NOT_IMPLEMENTED, WRITE_NOT_IMPLEMENTED, read_file, write_file


@pytest.mark.asyncio
async def test_read_write_bash_are_stubs() -> None:
    assert await read_file({"path": "notes.md"}) == NOT_IMPLEMENTED
    assert await write_file({"path": "notes.md", "content": "hi"}) == WRITE_NOT_IMPLEMENTED
    assert await bash({"command": "ls"}) == BASH_NOT_IMPLEMENTED


@pytest.mark.asyncio
async def test_stub_validation() -> None:
    assert "path is required" in await read_file({})
    assert "path is required" in await write_file({"content": "x"})
    assert "content is required" in await write_file({"path": "a.md"})
    assert "command is required" in await bash({})
