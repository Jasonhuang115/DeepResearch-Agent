from pathlib import Path

import pytest

from agent_service.workspace.local import LocalProvider
from agent_service.workspace.paths import glob_match, safe_conversation_id
from agent_service.workspace.protocol import PathEscapeError


def test_safe_conversation_id() -> None:
    assert safe_conversation_id("") == "default"
    assert safe_conversation_id("conv_1") == "conv_1"
    assert safe_conversation_id("..") != ".."
    assert "/" not in safe_conversation_id("../etc")
    assert safe_conversation_id("weird id") != "weird id"


def test_glob_match() -> None:
    assert glob_match("memory/notes.md", "**/*.md")
    assert glob_match("notes.md", "*.md")
    assert not glob_match("notes.txt", "*.md")
    with pytest.raises(PathEscapeError):
        glob_match("a.md", "../x")


@pytest.mark.asyncio
async def test_local_nested_write_and_list(tmp_path: Path) -> None:
    ws = await LocalProvider(tmp_path).ensure("c1")
    await ws.write_text("sub/a.md", "one")
    await ws.write_text("sub/b.txt", "two")
    assert await ws.list_files("**/*.md") == ["sub/a.md"]
    assert await ws.read_text("sub/a.md") == "one"


@pytest.mark.asyncio
async def test_local_bash_timeout(tmp_path: Path) -> None:
    ws = await LocalProvider(tmp_path).ensure("c1")
    result = await ws.run("sleep 2", timeout_sec=1)
    assert result.timed_out
