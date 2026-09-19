from agent_service.tools.registry import ToolRegistry
from agent_service.tools.web_search import web_search


def default_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register("web_search", web_search)
    return r
