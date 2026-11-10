from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select

from app.api.dependencies import CurrentUser, ObjectsDep, SessionDep
from app.domain.errors import not_found
from app.domain.models import Attachment, Conversation, Message, Run
from app.infra.objects import LocalObjectStore, attachment_key

router = APIRouter(prefix="/v1/attachments", tags=["attachments"])


@router.get("/{attachment_id}/download")
async def download(
    attachment_id: str,
    user: CurrentUser,
    session: SessionDep,
    objects: ObjectsDep,
) -> Response:
    row = (
        await session.execute(
            select(Attachment, Conversation)
            .join(Message, Message.id == Attachment.message_id)
            .join(Run, Run.id == Message.run_id)
            .join(Conversation, Conversation.id == Run.conversation_id)
            .where(
                Attachment.id == attachment_id,
                Conversation.user_id == user.id,
                Conversation.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise not_found("Attachment not found.")
    attachment, conversation = row
    key = attachment_key(user.id, conversation.id, attachment.id)
    if not await objects.exists(key):
        raise not_found("Attachment object not found.")
    if isinstance(objects, LocalObjectStore):
        data = await objects.get(key)
        disposition = f"attachment; filename*=UTF-8''{quote(attachment.filename)}"
        return Response(
            data,
            media_type=attachment.content_type,
            headers={"Content-Disposition": disposition},
        )
    return RedirectResponse(await objects.signed_url(key, 300), status_code=302)
