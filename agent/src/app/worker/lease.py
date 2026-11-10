from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import RunStatus
from app.domain.models import Run
from app.domain.util import utc_now
from app.infra.config import settings
from app.infra.redis import RedisStore

log = logging.getLogger(__name__)


async def renew(
    sessions: async_sessionmaker[AsyncSession],
    run_id: str,
    attempt_count: int,
    cancel: asyncio.Event,
) -> bool:
    async with sessions() as session, session.begin():
        run = await session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None or run.attempt_count != attempt_count:
            cancel.set()
            return False
        if run.status == RunStatus.CANCELLING:
            cancel.set()
        elif run.status != RunStatus.RUNNING:
            cancel.set()
            return False
        run.lease_expires_at = utc_now() + timedelta(seconds=settings.lease_seconds)
        return True


async def monitor(
    sessions: async_sessionmaker[AsyncSession],
    redis: RedisStore,
    run_id: str,
    attempt_count: int,
    cancel: asyncio.Event,
    stop: asyncio.Event,
) -> None:
    pubsub = None
    try:
        try:
            pubsub = await redis.subscribe_control(run_id)
        except Exception:
            log.warning("Redis control subscription unavailable", exc_info=True)
        renewed_at = 0.0
        while not stop.is_set():
            now = time.monotonic()
            if now - renewed_at >= settings.lease_refresh_seconds:
                if not await renew(sessions, run_id, attempt_count, cancel):
                    return
                renewed_at = now
            if pubsub is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=1)
                continue
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
            if message:
                cancel.set()
    finally:
        if pubsub is not None:
            await pubsub.unsubscribe()
            await pubsub.close()
