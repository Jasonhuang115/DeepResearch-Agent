from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.enums import RunStatus
from app.domain.models import Run, RunEvent
from app.domain.util import utc_now
from app.infra.redis import RedisStore

log = logging.getLogger(__name__)


class StaleWorkerError(RuntimeError):
    pass


async def next_seq(session: AsyncSession, run_id: str) -> int:
    current = await session.scalar(
        select(func.coalesce(func.max(RunEvent.seq), 0)).where(RunEvent.run_id == run_id)
    )
    return int(current or 0) + 1


def event_view(event: RunEvent) -> dict[str, Any]:
    return {
        "run_id": event.run_id,
        "seq": event.seq,
        "type": event.type,
        "payload": event.payload,
        "created_at": event.created_at.isoformat() + "Z",
    }


async def add_event_locked(
    session: AsyncSession, run_id: str, typ: str, payload: dict[str, Any]
) -> RunEvent:
    event = RunEvent(
        run_id=run_id,
        seq=await next_seq(session, run_id),
        type=typ,
        payload=payload,
        created_at=utc_now(),
    )
    session.add(event)
    await session.flush()
    return event


class EventWriter:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        redis: RedisStore,
        run_id: str,
        attempt_count: int,
    ) -> None:
        self.sessions = sessions
        self.redis = redis
        self.run_id = run_id
        self.attempt_count = attempt_count

    async def emit(self, typ: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self.sessions() as session, session.begin():
            run = await session.scalar(select(Run).where(Run.id == self.run_id).with_for_update())
            if (
                run is None
                or run.status not in {RunStatus.RUNNING, RunStatus.CANCELLING}
                or run.attempt_count != self.attempt_count
                or run.lease_expires_at is None
                or run.lease_expires_at <= utc_now()
            ):
                raise StaleWorkerError(f"run {self.run_id} is no longer owned by this worker")
            event = await add_event_locked(session, self.run_id, typ, payload or {})
            view = event_view(event)
        try:
            await self.redis.publish_event(self.run_id, view)
        except Exception:
            log.warning("Redis event publication failed", exc_info=True)
        return view
