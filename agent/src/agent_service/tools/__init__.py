from collections.abc import Awaitable, Callable
from typing import Any

from agent_service.tools.bash import BASH_DESCRIPTION, BASH_PARAMETERS, bash
from agent_service.tools.fs import (
    DESCRIPTION as READ_DESCRIPTION,
    EDIT_DESCRIPTION,
    EDIT_PARAMETERS,
    GLOB_DESCRIPTION,
    GLOB_PARAMETERS,
    GREP_DESCRIPTION,
    GREP_PARAMETERS,
    PARAMETERS as READ_PARAMETERS,
    WRITE_DESCRIPTION,
    WRITE_PARAMETERS,
    edit_file,
    glob_files,
    grep_files,
    read_file,
    write_file,
)
from agent_service.tools.registry import ToolRegistry, ToolSpec
from agent_service.tools.web_search import DESCRIPTION, PARAMETERS, web_search
from agent_service.workspace.protocol import Workspace

ToolFn = Callable[[dict[str, Any]], Awaitable[str]]


def _bound(fn: Callable[..., Awaitable[str]], workspace: Workspace | None) -> ToolFn:
    async def inner(args: dict[str, Any]) -> str:
        if workspace is None:
            return "error: workspace is not available"
        return await fn(workspace, args)

    return inner


def default_registry(workspace: Workspace | None = None) -> ToolRegistry:
    r = ToolRegistry()
    r.register("web_search", web_search, description=DESCRIPTION, parameters=PARAMETERS)
    r.register("Read", _bound(read_file, workspace), description=READ_DESCRIPTION, parameters=READ_PARAMETERS)
    r.register("Write", _bound(write_file, workspace), description=WRITE_DESCRIPTION, parameters=WRITE_PARAMETERS)
    r.register("Edit", _bound(edit_file, workspace), description=EDIT_DESCRIPTION, parameters=EDIT_PARAMETERS)
    r.register("Glob", _bound(glob_files, workspace), description=GLOB_DESCRIPTION, parameters=GLOB_PARAMETERS)
    r.register("Grep", _bound(grep_files, workspace), description=GREP_DESCRIPTION, parameters=GREP_PARAMETERS)
    r.register("Bash", _bound(bash, workspace), description=BASH_DESCRIPTION, parameters=BASH_PARAMETERS)
    return r


__all__ = ["ToolRegistry", "ToolSpec", "default_registry", "web_search"]
