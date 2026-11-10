from __future__ import annotations

import base64
import json
from datetime import datetime

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import not_found
from app.domain.models import Conversation
from app.domain.util import new_id, utc_now


async def create_conversation(session: AsyncSession, user_id: str) -> Conversation:
    now = utc_now()
    conversation = Conversation(
        id=new_id(),
        user_id=user_id,
        title="新会话",
        created_at=now,
        updated_at=now,
    )
    session.add(conversation)
    await session.commit()
    return conversation


def owned_conversation_query(user_id: str, conversation_id: str) -> Select[tuple[Conversation]]:
    return select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user_id,
        Conversation.deleted_at.is_(None),
    )


async def get_owned_conversation(
    session: AsyncSession, user_id: str, conversation_id: str, *, lock: bool = False
) -> Conversation:
    query = owned_conversation_query(user_id, conversation_id)
    if lock:
        query = query.with_for_update()
    conversation = await session.scalar(query)
    if conversation is None:
        raise not_found("Conversation not found.")
    return conversation


def encode_cursor(updated_at: datetime, conversation_id: str) -> str:
    raw = json.dumps([updated_at.isoformat(), conversation_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        timestamp, conversation_id = json.loads(base64.urlsafe_b64decode(padded).decode())
        return datetime.fromisoformat(timestamp), str(conversation_id)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid cursor") from exc


async def list_conversations(
    session: AsyncSession, user_id: str, limit: int, cursor: str | None
) -> list[Conversation]:
    query = select(Conversation).where(
        Conversation.user_id == user_id, Conversation.deleted_at.is_(None)
    )
    if cursor:
        timestamp, conversation_id = decode_cursor(cursor)
        query = query.where(
            or_(
                Conversation.updated_at < timestamp,
                and_(
                    Conversation.updated_at == timestamp,
                    Conversation.id < conversation_id,
                ),
            )
        )
    query = query.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(limit)
    return list((await session.scalars(query)).all())


def title_from_message(content: str) -> str:
    title = " ".join(content.split()).strip()
    return (title[:80] or "附件研究").strip()
