from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AuthInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    created_at: datetime


class TokenView(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserView


class ConversationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    status: str
    attempt_count: int
    created_at: datetime


class ConversationDetail(ConversationView):
    active_run: RunView | None = None


class AttachmentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    content_type: str
    size_bytes: int


class MessageView(BaseModel):
    id: str
    conversation_id: str
    run_id: str
    role: str
    content: str
    created_at: datetime
    attachments: list[AttachmentView] = Field(default_factory=list)


class MessageAccepted(BaseModel):
    run_id: str
    message_id: str
    status: str
