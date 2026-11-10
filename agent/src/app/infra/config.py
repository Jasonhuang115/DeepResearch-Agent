from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agent_service.envfile import load_repo_env

load_repo_env()


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _origins() -> tuple[str, ...]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    return tuple(value.strip() for value in raw.split(",") if value.strip())


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "mysql+asyncmy://research:research@127.0.0.1:3306/research?charset=utf8mb4",
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-change-me-please-use-32-bytes-min")
    access_token_seconds: int = int(os.getenv("ACCESS_TOKEN_SECONDS", "900"))
    refresh_token_seconds: int = int(os.getenv("REFRESH_TOKEN_SECONDS", "2592000"))
    refresh_cookie_name: str = os.getenv("REFRESH_COOKIE_NAME", "dra_refresh")
    cookie_secure: bool = _bool("COOKIE_SECURE", False)
    cors_origins: tuple[str, ...] = _origins()
    lease_seconds: int = int(os.getenv("RUN_LEASE_SECONDS", "30"))
    lease_refresh_seconds: int = int(os.getenv("RUN_LEASE_REFRESH_SECONDS", "10"))
    worker_poll_seconds: float = float(os.getenv("WORKER_POLL_SECONDS", "1"))
    worker_concurrency: int = int(os.getenv("WORKER_CONCURRENCY", "2"))
    max_files: int = int(os.getenv("UPLOAD_MAX_FILES", "10"))
    max_file_bytes: int = int(os.getenv("UPLOAD_MAX_BYTES", str(25 * 1024 * 1024)))
    max_upload_bytes: int = int(os.getenv("UPLOAD_TOTAL_MAX_BYTES", str(100 * 1024 * 1024)))
    object_store: str = os.getenv("OBJECT_STORE", "local")
    object_root: Path = Path(os.getenv("OBJECT_ROOT", "../data/objects"))
    oss_access_key_id: str = os.getenv("OSS_ACCESS_KEY_ID", "")
    oss_access_key_secret: str = os.getenv("OSS_ACCESS_KEY_SECRET", "")
    oss_bucket: str = os.getenv("OSS_BUCKET", "")
    oss_endpoint: str = os.getenv("OSS_ENDPOINT", "")
    e2b_api_key: str = os.getenv("E2B_API_KEY", "")
    sandbox_mode: str = os.getenv("SANDBOX_MODE", "local")
    sandbox_ttl_seconds: int = int(os.getenv("SANDBOX_TTL_SECONDS", "3300"))


settings = Settings()
