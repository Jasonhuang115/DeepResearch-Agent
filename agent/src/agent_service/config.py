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


settings = Settings()
