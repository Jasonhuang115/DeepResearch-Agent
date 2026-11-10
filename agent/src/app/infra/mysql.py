from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.infra.config import settings


def build_engine(database_url: str | None = None) -> AsyncEngine:
    url = database_url or settings.database_url
    options: dict[str, object] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options.pop("pool_pre_ping")
    else:
        options["isolation_level"] = "READ COMMITTED"
        options["connect_args"] = {"init_command": "SET time_zone = '+00:00'"}
    return create_async_engine(url, **options)


engine = build_engine()
session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
