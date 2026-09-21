from collections.abc import Awaitable, Callable
from typing import Any

from agent_service.sources.ledger import SourceLedger
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
from agent_service.tools.overflow import Overflow
from agent_service.tools.registry import ToolRegistry, ToolSpec
from agent_service.tools.web_fetch import DESCRIPTION as FETCH_DESCRIPTION
from agent_service.tools.web_fetch import PARAMETERS as FETCH_PARAMETERS
from agent_service.tools.web_fetch import web_fetch
from agent_service.tools.web_search import DESCRIPTION, PARAMETERS, Searcher, web_search
from agent_service.workspace.protocol import Workspace

ToolFn = Callable[[dict[str, Any]], Awaitable[str]]


def _bound(fn: Callable[..., Awaitable[str]], workspace: Workspace | None) -> ToolFn:
    async def inner(args: dict[str, Any]) -> str:
        if workspace is None:
            return "error: workspace is not available"
        return await fn(workspace, args)

    return inner


def _bound_web(
    fn: Callable[..., Awaitable[str]],
    workspace: Workspace | None,
    ledger: SourceLedger | None,
    **extra: Any,
) -> ToolFn:
    async def inner(args: dict[str, Any]) -> str:
        if workspace is None:
            return "error: workspace is not available"
        book = ledger or SourceLedger(workspace)
        return await fn(workspace, book, args, **extra)

    return inner


def default_registry(
    workspace: Workspace | None = None,
    *,
    ledger: SourceLedger | None = None,
    searcher: Searcher | None = None,
    fetcher: Any | None = None,
    overflow: Overflow | None = None,
) -> ToolRegistry:
    if workspace is not None and ledger is None:
        ledger = SourceLedger(workspace)
    r = ToolRegistry()
    r.overflow = overflow
    r.register(
        "web_search",
        _bound_web(web_search, workspace, ledger, searcher=searcher),
        description=DESCRIPTION,
        parameters=PARAMETERS,
    )
    r.register(
        "web_fetch",
        _bound_web(web_fetch, workspace, ledger, getter=fetcher),
        description=FETCH_DESCRIPTION,
        parameters=FETCH_PARAMETERS,
    )
    r.register("Read", _bound(read_file, workspace), description=READ_DESCRIPTION, parameters=READ_PARAMETERS)
    r.register("Write", _bound(write_file, workspace), description=WRITE_DESCRIPTION, parameters=WRITE_PARAMETERS)
    r.register("Edit", _bound(edit_file, workspace), description=EDIT_DESCRIPTION, parameters=EDIT_PARAMETERS)
    r.register("Glob", _bound(glob_files, workspace), description=GLOB_DESCRIPTION, parameters=GLOB_PARAMETERS)
    r.register("Grep", _bound(grep_files, workspace), description=GREP_DESCRIPTION, parameters=GREP_PARAMETERS)
    r.register("Bash", _bound(bash, workspace), description=BASH_DESCRIPTION, parameters=BASH_PARAMETERS)
    return r


__all__ = ["ToolRegistry", "ToolSpec", "default_registry", "web_search"]
