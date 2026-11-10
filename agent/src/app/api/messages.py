from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, UploadFile
from sqlalchemy import case, select
from sqlalchemy.orm import selectinload

from app.api.dependencies import CurrentUser, ObjectsDep, SessionDep
from app.domain.enums import ACTIVE_RUN_STATUSES, MessageRole, RunStatus
from app.domain.errors import AppError, conflict
from app.domain.models import Attachment, Message, Run
from app.domain.schemas import AttachmentView, MessageAccepted, MessageView
from app.domain.util import new_id, utc_now
from app.infra.objects import attachment_key
from app.services.conversations import get_owned_conversation, title_from_message
from app.services.uploads import read_uploads

router = APIRouter(prefix="/v1/conversations", tags=["messages"])


async def _existing_run(session: SessionDep, conversation_id: str, key: str) -> Run | None:
    return await session.scalar(
        select(Run).where(
            Run.conversation_id == conversation_id,
            Run.idempotency_key == key,
        )
    )


async def _accepted_for_run(session: SessionDep, run: Run) -> dict:
    message_id = await session.scalar(
        select(Message.id).where(Message.run_id == run.id, Message.role == MessageRole.USER)
    )
    return MessageAccepted(
        run_id=run.id,
        message_id=str(message_id),
        status=run.status,
    ).model_dump(mode="json")


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: str,
    user: CurrentUser,
    session: SessionDep,
    limit: int = 100,
) -> dict:
    await get_owned_conversation(session, user.id, conversation_id)
    limit = min(max(limit, 1), 200)
    role_order = case((Message.role == MessageRole.USER, 0), else_=1)
    rows = list(
        (
            await session.scalars(
                select(Message)
                .join(Run, Run.id == Message.run_id)
                .where(Run.conversation_id == conversation_id)
                .options(selectinload(Message.attachments))
                .order_by(Run.created_at.asc(), role_order.asc(), Message.created_at.asc())
                .limit(limit)
            )
        ).unique()
    )
    items = [
        MessageView(
            id=row.id,
            conversation_id=conversation_id,
            run_id=row.run_id,
            role=row.role,
            content=row.content,
            created_at=row.created_at,
            attachments=[AttachmentView.model_validate(item) for item in row.attachments],
        ).model_dump(mode="json")
        for row in rows
    ]
    return {"data": {"items": items, "next_cursor": None}}


@router.post("/{conversation_id}/messages", status_code=202)
async def create_message(
    conversation_id: str,
    user: CurrentUser,
    session: SessionDep,
    objects: ObjectsDep,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=64)
    ],
    content: Annotated[str, Form()] = "",
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> dict:
    body = content.strip()
    uploads = await read_uploads(files or [])
    if not body and not uploads:
        raise AppError(422, "empty_message", "A message or attachment is required.")

    conversation = await get_owned_conversation(session, user.id, conversation_id)
    existing = await _existing_run(session, conversation.id, idempotency_key)
    if existing:
        return {"data": await _accepted_for_run(session, existing)}

    run_id = new_id()
    message_id = new_id()
    attachment_ids = [new_id() for _ in uploads]
    stored_keys: list[str] = []
    try:
        for attachment_id, upload in zip(attachment_ids, uploads, strict=True):
            key = attachment_key(user.id, conversation.id, attachment_id)
            await objects.put(key, upload.data)
            stored_keys.append(key)

        await session.rollback()
        async with session.begin():
            conversation = await get_owned_conversation(
                session, user.id, conversation_id, lock=True
            )
            existing = await _existing_run(session, conversation.id, idempotency_key)
            if existing:
                accepted = await _accepted_for_run(session, existing)
            else:
                active = await session.scalar(
                    select(Run.id).where(
                        Run.conversation_id == conversation.id,
                        Run.status.in_(ACTIVE_RUN_STATUSES),
                    )
                )
                if active:
                    raise conflict(
                        "conversation_busy",
                        "This conversation already has an active run.",
                    )
                now = utc_now()
                run = Run(
                    id=run_id,
                    conversation_id=conversation.id,
                    idempotency_key=idempotency_key,
                    status=RunStatus.QUEUED,
                    attempt_count=0,
                    created_at=now,
                )
                message = Message(
                    id=message_id,
                    run_id=run.id,
                    role=MessageRole.USER,
                    content=body,
                    created_at=now,
                )
                session.add_all([run, message])
                session.add_all(
                    [
                        Attachment(
                            id=attachment_id,
                            message_id=message.id,
                            filename=upload.filename,
                            content_type=upload.content_type,
                            size_bytes=upload.size,
                        )
                        for attachment_id, upload in zip(attachment_ids, uploads, strict=True)
                    ]
                )
                if conversation.title == "新会话":
                    conversation.title = title_from_message(body)
                conversation.updated_at = now
                accepted = MessageAccepted(
                    run_id=run.id, message_id=message.id, status=run.status
                ).model_dump(mode="json")
        if existing:
            await asyncio.gather(*(objects.delete(key) for key in stored_keys))
        return {"data": accepted}
    except Exception:
        await asyncio.gather(*(objects.delete(key) for key in stored_keys), return_exceptions=True)
        raise
