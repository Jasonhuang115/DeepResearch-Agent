from __future__ import annotations

import os
import tempfile
from pathlib import Path


class Settings:
    http_addr: str = os.getenv("AGENT_HTTP_ADDR", "127.0.0.1:8001")
    kafka_brokers: str = os.getenv("KAFKA_BROKERS", "127.0.0.1:9092")
    commands_topic: str = os.getenv("KAFKA_COMMANDS_TOPIC", "research.run.commands")
    events_topic: str = os.getenv("KAFKA_EVENTS_TOPIC", "research.run.events")
    group: str = os.getenv("KAFKA_GROUP", "agent")
    max_report_chars: int = int(os.getenv("MAX_REPORT_CHARS", "200000"))
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "")
    openai_thinking: str = os.getenv("OPENAI_THINKING", "")
    openai_reasoning_effort: str = os.getenv("OPENAI_REASONING_EFFORT", "")
    max_turns: int = int(os.getenv("AGENT_MAX_TURNS", "8"))
    workspace_mode: str = os.getenv("AGENT_WORKSPACE", "auto")
    workspace_root: str = os.getenv(
        "AGENT_WORKSPACE_ROOT",
        str(Path(tempfile.gettempdir()) / "research-workspaces"),
    )
    e2b_api_key: str = os.getenv("E2B_API_KEY", "")
    e2b_timeout_sec: int = int(os.getenv("E2B_TIMEOUT_SEC", "3600"))
    sandbox_redis_ttl_sec: int = int(os.getenv("AGENT_SANDBOX_REDIS_TTL_SEC", "3300"))
    redis_addr: str = os.getenv("REDIS_ADDR", "127.0.0.1:6379")
    web_search_provider: str = os.getenv("WEB_SEARCH_PROVIDER", "mock")
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
    web_search_max_results: int = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
    fetch_timeout_sec: int = int(os.getenv("AGENT_FETCH_TIMEOUT_SEC", "20"))
    fetch_max_bytes: int = int(os.getenv("AGENT_FETCH_MAX_BYTES", "2000000"))
    upload_dir: str = os.getenv("UPLOAD_DIR", "data/uploads")
    tool_result_max_chars: int = int(os.getenv("AGENT_TOOL_RESULT_MAX_CHARS", "10000"))
    context_input_budget: int = int(os.getenv("AGENT_CONTEXT_INPUT_BUDGET", "100000"))
    keepalive_sec: int = int(os.getenv("AGENT_KEEPALIVE_SEC", "60"))
    durable_root: str = os.getenv("AGENT_DURABLE_ROOT", "data/workspaces")
    oss_access_key_id: str = os.getenv("OSS_ACCESS_KEY_ID", "")
    oss_access_key_secret: str = os.getenv("OSS_ACCESS_KEY_SECRET", "")
    oss_bucket: str = os.getenv("OSS_BUCKET", "")
    oss_endpoint: str = os.getenv("OSS_ENDPOINT", "")
    oss_prefix: str = os.getenv("OSS_PREFIX", "tenants/")


def resolve_upload_dir(raw: str | None = None) -> Path:
    value = (raw if raw is not None else settings.upload_dir) or "data/uploads"
    path = Path(value)
    if path.is_absolute():
        return path
    cwd = Path.cwd()
    if value == "data/uploads" and (cwd / "pyproject.toml").exists():
        return (cwd.parent / "data" / "uploads").resolve()
    return (cwd / path).resolve()


def resolve_durable_root(raw: str | None = None) -> Path:
    value = (raw if raw is not None else settings.durable_root) or "data/workspaces"
    path = Path(value)
    if path.is_absolute():
        return path
    cwd = Path.cwd()
    if value == "data/workspaces" and (cwd / "pyproject.toml").exists():
        return (cwd.parent / "data" / "workspaces").resolve()
    return (cwd / path).resolve()


settings = Settings()
