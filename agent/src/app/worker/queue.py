from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.domain.enums import MessageRole, RunStatus
from app.domain.models import Conversation, Message, Run
from app.domain.util import utc_now
from app.infra.config import settings
from app.infra.objects import ObjectStore, attachment_key

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Claim:
    run_id: str
    conversation_id: str
    user_id: str
    attempt_count: int


async def claim_next(sessions: async_sessionmaker[AsyncSession]) -> Claim | None:
    async with sessions() as session, session.begin():
        run = await session.scalar(
            select(Run)
            .join(Conversation, Conversation.id == Run.conversation_id)
            .where(
                Run.status == RunStatus.QUEUED,
                Run.attempt_count < 2,
                Conversation.deleted_at.is_(None),
            )
            .order_by(Run.created_at, Run.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if run is None:
            return None
        conversation = await session.get(Conversation, run.conversation_id)
        if conversation is None:
            return None
        run.status = RunStatus.RUNNING
        run.attempt_count += 1
        run.lease_expires_at = utc_now() + timedelta(seconds=settings.lease_seconds)
        return Claim(run.id, run.conversation_id, conversation.user_id, run.attempt_count)


async def build_command(
    sessions: async_sessionmaker[AsyncSession], objects: ObjectStore, claim: Claim
) -> dict[str, Any]:
    async with sessions() as session:
        messages = list(
            (
                await session.scalars(
                    select(Message)
                    .join(Run, Run.id == Message.run_id)
                    .where(Run.conversation_id == claim.conversation_id)
                    .order_by(Run.created_at, Message.created_at)
                )
            ).all()
        )
        current = await session.scalar(
            select(Message)
            .where(Message.run_id == claim.run_id, Message.role == MessageRole.USER)
            .options(selectinload(Message.attachments))
        )
        if current is None:
            raise RuntimeError(f"run {claim.run_id} has no user message")
        refs = []
        for attachment in current.attachments:
            key = attachment_key(claim.user_id, claim.conversation_id, attachment.id)
            refs.append(
                {
                    "id": attachment.id,
                    "filename": attachment.filename,
                    "content_type": attachment.content_type,
                    "size": attachment.size_bytes,
                    "data": await objects.get(key),
                }
            )
    return {
        "run_id": claim.run_id,
        "conversation_id": claim.conversation_id,
        "user_id": claim.user_id,
        "messages": [{"role": item.role, "content": item.content} for item in messages],
        "request": {"content": current.content, "attachments": refs},
    }
