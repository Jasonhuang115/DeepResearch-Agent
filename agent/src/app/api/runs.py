from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies import CurrentUser, RedisDep, SessionDep
from app.domain.enums import TERMINAL_RUN_STATUSES, RunStatus
from app.domain.errors import AppError, not_found
from app.domain.models import Conversation, Run, RunEvent
from app.domain.schemas import RunView
from app.infra.redis import RedisStore
from app.services.events import add_event_locked, event_view

router = APIRouter(prefix="/v1/runs", tags=["runs"])


async def _owned_run(
    session: AsyncSession, user_id: str, run_id: str, *, lock: bool = False
) -> Run:
    query = (
        select(Run)
        .join(Conversation, Conversation.id == Run.conversation_id)
        .where(
            Run.id == run_id,
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
    )
    if lock:
        query = query.with_for_update()
    run = await session.scalar(query)
    if run is None:
        raise not_found("Run not found.")
    return run


@router.get("/{run_id}")
async def get_run(run_id: str, user: CurrentUser, session: SessionDep) -> dict:
    run = await _owned_run(session, user.id, run_id)
    return {"data": RunView.model_validate(run).model_dump(mode="json")}


@router.post("/{run_id}/cancel", status_code=202)
async def cancel_run(
    run_id: str,
    user: CurrentUser,
    session: SessionDep,
    redis: RedisDep,
) -> dict:
    published: dict | None = None
    notify = False
    await session.rollback()
    async with session.begin():
        run = await _owned_run(session, user.id, run_id, lock=True)
        if run.status == RunStatus.QUEUED:
            run.status = RunStatus.CANCELLED
            event = await add_event_locked(
                session, run.id, "run.finished", {"status": RunStatus.CANCELLED}
            )
            published = event_view(event)
        elif run.status == RunStatus.RUNNING:
            run.status = RunStatus.CANCELLING
            notify = True
        elif run.status == RunStatus.CANCELLING:
            notify = True
    if published:
        with contextlib.suppress(Exception):
            await redis.publish_event(run_id, published)
    if notify:
        with contextlib.suppress(Exception):
            await redis.publish_cancel(run_id)
    return {"data": RunView.model_validate(run).model_dump(mode="json")}


def _sse(event: dict) -> str:
    data = json.dumps(event["payload"], ensure_ascii=False, separators=(",", ":"))
    return f"id: {event['seq']}\nevent: {event['type']}\ndata: {data}\n\n"


async def _load_events(
    sessions: async_sessionmaker[AsyncSession], run_id: str, after: int
) -> tuple[list[dict], str | None]:
    async with sessions() as session:
        rows = list(
            (
                await session.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.seq > after)
                    .order_by(RunEvent.seq)
                    .limit(500)
                )
            ).all()
        )
        status = await session.scalar(select(Run.status).where(Run.id == run_id))
    return [event_view(row) for row in rows], str(status) if status else None


async def _stream(
    sessions: async_sessionmaker[AsyncSession],
    redis: RedisStore,
    run_id: str,
    after: int,
) -> AsyncIterator[str]:
    pubsub = None
    try:
        try:
            pubsub = await redis.subscribe_events(run_id)
        except Exception:
            pubsub = None
        last = after
        heartbeat = time.monotonic()
        while True:
            events, status = await _load_events(sessions, run_id, last)
            for event in events:
                if event["seq"] <= last:
                    continue
                last = int(event["seq"])
                yield _sse(event)
            if status in TERMINAL_RUN_STATUSES and not events:
                return
            if time.monotonic() - heartbeat >= 15:
                yield ": heartbeat\n\n"
                heartbeat = time.monotonic()
            if pubsub is None:
                await asyncio.sleep(1)
            else:
                try:
                    await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
                except Exception:
                    await pubsub.close()
                    pubsub = None
    except asyncio.CancelledError:
        raise
    finally:
        if pubsub is not None:
            await pubsub.unsubscribe()
            await pubsub.close()


@router.get("/{run_id}/events")
async def stream_events(
    run_id: str,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    await _owned_run(session, user.id, run_id)
    try:
        after = max(0, int(last_event_id or "0"))
    except ValueError as exc:
        raise AppError(422, "invalid_event_id", "Last-Event-ID must be an integer.") from exc
    return StreamingResponse(
        _stream(request.app.state.sessions, request.app.state.redis, run_id, after),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
