from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_service.workspace.e2b import try_sdk_factory
from app.domain.enums import ACTIVE_RUN_STATUSES
from app.domain.models import Conversation, Run
from app.infra.config import settings
from app.infra.objects import ObjectStore, conversation_prefix
from app.infra.redis import RedisStore

log = logging.getLogger(__name__)


async def cleanup_deleted(
    sessions: async_sessionmaker[AsyncSession],
    redis: RedisStore,
    objects: ObjectStore,
) -> int:
    async with sessions() as session:
        rows = list(
            (
                await session.scalars(
                    select(Conversation)
                    .where(Conversation.deleted_at.is_not(None))
                    .order_by(Conversation.deleted_at)
                    .limit(10)
                )
            ).all()
        )
    cleaned = 0
    for conversation in rows:
        async with sessions() as session:
            active = await session.scalar(
                select(Run.id).where(
                    Run.conversation_id == conversation.id,
                    Run.status.in_(ACTIVE_RUN_STATUSES),
                )
            )
        if active:
            continue
        try:
            await objects.delete_prefix(
                conversation_prefix(conversation.user_id, conversation.id)
            )
            await _destroy_sandbox(redis, conversation.user_id, conversation.id)
            async with sessions() as session, session.begin():
                locked = await session.scalar(
                    select(Conversation)
                    .where(Conversation.id == conversation.id)
                    .with_for_update()
                )
                if locked is not None:
                    await session.delete(locked)
            cleaned += 1
        except Exception:
            log.warning("conversation cleanup failed for %s", conversation.id, exc_info=True)
    return cleaned


async def _destroy_sandbox(redis: RedisStore, user_id: str, conversation_id: str) -> None:
    sandbox_id = await redis.sandbox_get(user_id, conversation_id)
    if sandbox_id and settings.sandbox_mode == "e2b" and settings.e2b_api_key:
        factory = try_sdk_factory(settings.e2b_api_key)
        if factory is not None:
            try:
                client = await factory.connect(sandbox_id)
                kill = getattr(client, "kill", None)
                if kill is not None:
                    await kill()
            except Exception:
                log.warning("E2B sandbox cleanup failed", exc_info=True)
    await redis.sandbox_delete(user_id, conversation_id)
