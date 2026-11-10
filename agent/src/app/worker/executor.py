from __future__ import annotations

import asyncio
import contextlib
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.runner import ResearchResult, execute_research
from app.domain.enums import MessageRole, RunStatus
from app.domain.models import Message, Run
from app.domain.util import new_id, utc_now
from app.infra.objects import ObjectStore
from app.infra.redis import RedisStore
from app.services.events import (
    EventWriter,
    StaleWorkerError,
    add_event_locked,
    event_view,
)
from app.worker.lease import monitor
from app.worker.queue import Claim, build_command

log = logging.getLogger(__name__)


async def finalize(
    sessions: async_sessionmaker[AsyncSession],
    redis: RedisStore,
    claim: Claim,
    result: ResearchResult,
) -> None:
    published: list[dict] = []
    async with sessions() as session, session.begin():
        run = await session.scalar(select(Run).where(Run.id == claim.run_id).with_for_update())
        if run is None or run.attempt_count != claim.attempt_count:
            raise StaleWorkerError(f"run {claim.run_id} was reassigned")
        if run.status == RunStatus.CANCELLING or result.status == RunStatus.CANCELLED:
            status = RunStatus.CANCELLED
        elif result.status == RunStatus.SUCCEEDED:
            status = RunStatus.SUCCEEDED
        else:
            status = RunStatus.FAILED
        if status == RunStatus.SUCCEEDED:
            session.add(
                Message(
                    id=new_id(),
                    run_id=run.id,
                    role=MessageRole.ASSISTANT,
                    content=result.content,
                    created_at=utc_now(),
                )
            )
            completed = await add_event_locked(
                session, run.id, "message.completed", {"content": result.content}
            )
            published.append(event_view(completed))
        run.status = status
        run.lease_expires_at = None
        payload = {"status": status}
        if result.error:
            payload["error"] = result.error
        finished = await add_event_locked(session, run.id, "run.finished", payload)
        published.append(event_view(finished))
    for event in published:
        try:
            await redis.publish_event(claim.run_id, event)
        except Exception:
            log.warning("Redis final event publication failed", exc_info=True)


async def execute_claim(
    sessions: async_sessionmaker[AsyncSession],
    redis: RedisStore,
    objects: ObjectStore,
    claim: Claim,
) -> None:
    cancel = asyncio.Event()
    stop = asyncio.Event()
    lease_task = asyncio.create_task(
        monitor(sessions, redis, claim.run_id, claim.attempt_count, cancel, stop),
        name=f"lease-{claim.run_id}",
    )
    writer = EventWriter(sessions, redis, claim.run_id, claim.attempt_count)
    try:
        command = await build_command(sessions, objects, claim)
        result = await execute_research(
            command=command,
            writer=writer,
            cancel=cancel,
            redis=redis,
            objects=objects,
            user_id=claim.user_id,
            attempt_count=claim.attempt_count,
        )
        await finalize(sessions, redis, claim, result)
    except StaleWorkerError:
        log.info("run %s lost its lease", claim.run_id)
    except Exception as exc:
        log.exception("run %s failed", claim.run_id)
        try:
            await writer.emit("error", {"message": str(exc)})
            await finalize(
                sessions,
                redis,
                claim,
                ResearchResult(RunStatus.FAILED, "", str(exc)),
            )
        except StaleWorkerError:
            pass
    finally:
        stop.set()
        lease_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await lease_task
