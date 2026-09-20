from pathlib import Path

import pytest

from agent_service.tools import default_registry
from agent_service.tools.bash import bash
from agent_service.tools.fs import edit_file, glob_files, grep_files, read_file, write_file
from agent_service.workspace.local import LocalDirWorkspace, LocalProvider


@pytest.fixture
async def ws(tmp_path: Path) -> LocalDirWorkspace:
    return await LocalProvider(tmp_path).ensure("conv_test")


@pytest.mark.asyncio
async def test_registry_requires_workspace_for_fs_tools() -> None:
    tools = default_registry()
    assert tools.names() == ["web_search", "Read", "Write", "Edit", "Glob", "Grep", "Bash"]
    assert await tools.get("Read")({"path": "a.md"}) == "error: workspace is not available"


@pytest.mark.asyncio
async def test_write_read_roundtrip(ws: LocalDirWorkspace) -> None:
    assert "wrote" in await write_file(ws, {"path": "notes.md", "content": "hello\nworld"})
    text = await read_file(ws, {"path": "notes.md"})
    assert "hello" in text
    assert "world" in text
    assert "1|" in text


@pytest.mark.asyncio
async def test_read_offset_limit(ws: LocalDirWorkspace) -> None:
    await write_file(ws, {"path": "n.md", "content": "a\nb\nc\n"})
    text = await read_file(ws, {"path": "n.md", "offset": 1, "limit": 1})
    assert "b" in text
    assert "a" not in text
    assert "c" not in text


@pytest.mark.asyncio
async def test_validation_errors(ws: LocalDirWorkspace) -> None:
    assert "path is required" in await read_file(ws, {})
    assert "path is required" in await write_file(ws, {"content": "x"})
    assert "content is required" in await write_file(ws, {"path": "a.md"})
    assert "command is required" in await bash(ws, {})
    assert "file not found" in await read_file(ws, {"path": "missing.md"})


@pytest.mark.asyncio
async def test_path_jail(ws: LocalDirWorkspace, tmp_path: Path) -> None:
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    assert "escapes workspace" in await read_file(ws, {"path": "../outside.txt"})
    assert "escapes workspace" in await write_file(
        ws, {"path": "foo/../../outside.txt", "content": "nope"}
    )
    assert "escapes workspace" in await read_file(ws, {"path": "/etc/passwd"})
    assert (tmp_path / "outside.txt").read_text(encoding="utf-8") == "secret"


@pytest.mark.asyncio
async def test_edit_glob_grep(ws: LocalDirWorkspace) -> None:
    await write_file(ws, {"path": "memory/notes.md", "content": "alpha\nbeta\nalpha\n"})
    await write_file(ws, {"path": "readme.txt", "content": "alpha only"})
    assert "not unique" in await edit_file(
        ws, {"path": "memory/notes.md", "old_string": "alpha", "new_string": "gamma"}
    )
    assert "2 replacements" in await edit_file(
        ws,
        {
            "path": "memory/notes.md",
            "old_string": "alpha",
            "new_string": "gamma",
            "replace_all": True,
        },
    )
    text = await ws.read_text("memory/notes.md")
    assert text == "gamma\nbeta\ngamma\n"
    matched = await glob_files(ws, {"pattern": "**/*.md"})
    assert "memory/notes.md" in matched
    assert "readme.txt" not in matched
    hits = await grep_files(ws, {"pattern": "gamma", "glob": "**/*.md"})
    assert "memory/notes.md:1:gamma" in hits
    assert "readme.txt" not in hits


@pytest.mark.asyncio
async def test_bash_cwd_and_clean_env(ws: LocalDirWorkspace, monkeypatch: pytest.MonkeyPatch) -> None:
    await write_file(ws, {"path": "seen.txt", "content": "inside"})
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("E2B_API_KEY", "e2b-secret")
    listed = await bash(ws, {"command": "cat seen.txt && pwd"})
    assert "inside" in listed
    assert "conv_test" in listed
    env = await bash(ws, {"command": "printenv OPENAI_API_KEY; printenv E2B_API_KEY; echo done"})
    assert "sk-secret" not in env
    assert "e2b-secret" not in env
    assert "done" in env


@pytest.mark.asyncio
async def test_bound_registry_uses_workspace(ws: LocalDirWorkspace) -> None:
    tools = default_registry(ws)
    await tools.get("Write")({"path": "a.md", "content": "hi"})
    text = await tools.get("Read")({"path": "a.md"})
    assert "hi" in text
