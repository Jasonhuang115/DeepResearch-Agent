from agent_service.tools.bash import BASH_DESCRIPTION, BASH_PARAMETERS, bash
from agent_service.tools.fs import (
    DESCRIPTION as READ_DESCRIPTION,
    PARAMETERS as READ_PARAMETERS,
    WRITE_DESCRIPTION,
    WRITE_PARAMETERS,
    read_file,
    write_file,
)
from agent_service.tools.registry import ToolRegistry, ToolSpec
from agent_service.tools.web_search import DESCRIPTION, PARAMETERS, web_search


def default_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register("web_search", web_search, description=DESCRIPTION, parameters=PARAMETERS)
    r.register("Read", read_file, description=READ_DESCRIPTION, parameters=READ_PARAMETERS)
    r.register("Write", write_file, description=WRITE_DESCRIPTION, parameters=WRITE_PARAMETERS)
    r.register("Bash", bash, description=BASH_DESCRIPTION, parameters=BASH_PARAMETERS)
    return r


__all__ = ["ToolRegistry", "ToolSpec", "default_registry", "web_search"]
