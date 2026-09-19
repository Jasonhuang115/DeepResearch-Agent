from __future__ import annotations

import os


class Settings:
    http_addr: str = os.getenv("AGENT_HTTP_ADDR", "127.0.0.1:8001")
    kafka_brokers: str = os.getenv("KAFKA_BROKERS", "127.0.0.1:9092")
    commands_topic: str = os.getenv("KAFKA_COMMANDS_TOPIC", "research.run.commands")
    events_topic: str = os.getenv("KAFKA_EVENTS_TOPIC", "research.run.events")
    group: str = os.getenv("KAFKA_GROUP", "agent")
    max_report_chars: int = int(os.getenv("MAX_REPORT_CHARS", "200000"))


settings = Settings()
