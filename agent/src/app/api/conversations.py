from __future__ import annotations

import contextlib

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.dependencies import CurrentUser, RedisDep, SessionDep
from app.domain.enums import ACTIVE_RUN_STATUSES, RunStatus
from app.domain.errors import AppError
from app.domain.models import Run
from app.domain.schemas import ConversationDetail, ConversationView, RunView
from app.domain.util import utc_now
from app.services.conversations import (
    create_conversation,
    encode_cursor,
    get_owned_conversation,
    list_conversations,
)
from app.services.events import add_event_locked, event_view

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


@router.get("")
async def list_items(
    user: CurrentUser,
    session: SessionDep,
    limit: int = Query(20, ge=1, le=50),
    cursor: str | None = None,
) -> dict:
    try:
        rows = await list_conversations(session, user.id, limit + 1, cursor)
    except ValueError as exc:
        raise AppError(422, "invalid_cursor", "The conversation cursor is invalid.") from exc
    more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if more and items:
        next_cursor = encode_cursor(items[-1].updated_at, items[-1].id)
    return {
        "data": {
            "items": [
                ConversationView.model_validate(row).model_dump(mode="json")
                for row in items
            ],
            "next_cursor": next_cursor,
        }
    }


@router.post("", status_code=201)
async def create(user: CurrentUser, session: SessionDep) -> dict:
    conversation = await create_conversation(session, user.id)
    return {"data": ConversationView.model_validate(conversation).model_dump(mode="json")}


@router.get("/{conversation_id}")
async def detail(conversation_id: str, user: CurrentUser, session: SessionDep) -> dict:
    conversation = await get_owned_conversation(session, user.id, conversation_id)
    run = await session.scalar(
        select(Run)
        .where(Run.conversation_id == conversation.id, Run.status.in_(ACTIVE_RUN_STATUSES))
        .order_by(Run.created_at.desc())
        .limit(1)
    )
    data = ConversationDetail(
        **ConversationView.model_validate(conversation).model_dump(),
        active_run=RunView.model_validate(run) if run else None,
    )
    return {"data": data.model_dump(mode="json")}


@router.delete("/{conversation_id}", status_code=202)
async def delete(
    conversation_id: str,
    user: CurrentUser,
    session: SessionDep,
    redis: RedisDep,
) -> dict:
    published: list[dict] = []
    await session.rollback()
    async with session.begin():
        conversation = await get_owned_conversation(
            session, user.id, conversation_id, lock=True
        )
        conversation.deleted_at = utc_now()
        runs = list(
            (
                await session.scalars(
                    select(Run)
                    .where(
                        Run.conversation_id == conversation.id,
                        Run.status.in_(ACTIVE_RUN_STATUSES),
                    )
                    .with_for_update()
                )
            ).all()
        )
        for run in runs:
            run.status = (
                RunStatus.CANCELLED
                if run.status == RunStatus.QUEUED
                else RunStatus.CANCELLING
            )
            if run.status == RunStatus.CANCELLED:
                event = await add_event_locked(
                    session, run.id, "run.finished", {"status": RunStatus.CANCELLED}
                )
                published.append(event_view(event))
    for event in published:
        with contextlib.suppress(Exception):
            await redis.publish_event(str(event["run_id"]), event)
    for run in runs:
        if run.status == RunStatus.CANCELLING:
            with contextlib.suppress(Exception):
                await redis.publish_cancel(run.id)
    return {"data": {"id": conversation_id, "deleted": True}}
