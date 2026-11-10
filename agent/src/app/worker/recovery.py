from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import RunStatus
from app.domain.models import Run
from app.domain.util import utc_now
from app.infra.redis import RedisStore
from app.services.events import add_event_locked, event_view

log = logging.getLogger(__name__)


async def recover_expired(
    sessions: async_sessionmaker[AsyncSession], redis: RedisStore
) -> int:
    published: list[dict] = []
    count = 0
    async with sessions() as session, session.begin():
        runs = list(
            (
                await session.scalars(
                    select(Run)
                    .where(
                        Run.status.in_((RunStatus.RUNNING, RunStatus.CANCELLING)),
                        Run.lease_expires_at.is_not(None),
                        Run.lease_expires_at <= utc_now(),
                    )
                    .with_for_update(skip_locked=True)
                    .limit(50)
                )
            ).all()
        )
        for run in runs:
            count += 1
            run.lease_expires_at = None
            if run.status == RunStatus.CANCELLING:
                run.status = RunStatus.CANCELLED
                event = await add_event_locked(
                    session, run.id, "run.finished", {"status": RunStatus.CANCELLED}
                )
                published.append(event_view(event))
            elif run.attempt_count < 2:
                run.status = RunStatus.QUEUED
                event = await add_event_locked(
                    session,
                    run.id,
                    "run.progress",
                    {"note": "worker lease expired; queued for one recovery"},
                )
                published.append(event_view(event))
            else:
                run.status = RunStatus.FAILED
                error = await add_event_locked(
                    session, run.id, "error", {"message": "worker lease expired twice"}
                )
                finished = await add_event_locked(
                    session,
                    run.id,
                    "run.finished",
                    {"status": RunStatus.FAILED, "error": "worker lease expired twice"},
                )
                published.extend((event_view(error), event_view(finished)))
    for event in published:
        try:
            await redis.publish_event(str(event["run_id"]), event)
        except Exception:
            log.warning("Redis recovery event publication failed", exc_info=True)
    return count
