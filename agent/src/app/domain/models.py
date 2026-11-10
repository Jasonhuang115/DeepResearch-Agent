from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, INTEGER, MEDIUMTEXT, TINYINT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.enums import MessageRole, RunStatus

ULID_LENGTH = 26
ID_TYPE = CHAR(ULID_LENGTH)
TIME_TYPE = DATETIME(fsp=3).with_variant(DateTime(), "sqlite")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("uk_users_email", "email", unique=True),)

    id: Mapped[str] = mapped_column(ID_TYPE, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIME_TYPE, nullable=False)

    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("idx_conv_user_updated", "user_id", "deleted_at", "updated_at", "id"),
    )

    id: Mapped[str] = mapped_column(ID_TYPE, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ID_TYPE, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIME_TYPE, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIME_TYPE, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(TIME_TYPE, nullable=True)

    user: Mapped[User] = relationship(back_populates="conversations")
    runs: Mapped[list[Run]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True
    )


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("conversation_id", "idempotency_key", name="uk_run_idempotency"),
        Index("idx_run_queue", "status", "lease_expires_at", "created_at"),
        Index("idx_run_conv_status", "conversation_id", "status"),
        Index("idx_run_conv_time", "conversation_id", "created_at", "id"),
        CheckConstraint(
            "status IN ('queued','running','cancelling','succeeded','failed','cancelled')",
            name="ck_run_status",
        ),
        CheckConstraint("attempt_count <= 2", name="ck_run_attempt_count"),
    )

    id: Mapped[str] = mapped_column(ID_TYPE, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ID_TYPE, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=RunStatus.QUEUED)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        TIME_TYPE, nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(
        TINYINT(unsigned=True).with_variant(Integer, "sqlite"), nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(TIME_TYPE, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="runs")
    messages: Mapped[list[Message]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )
    events: Mapped[list[RunEvent]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("run_id", "role", name="uk_message_run_role"),
        CheckConstraint("role IN ('user','assistant')", name="ck_message_role"),
    )

    id: Mapped[str] = mapped_column(ID_TYPE, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ID_TYPE, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=MessageRole.USER)
    content: Mapped[str] = mapped_column(
        MEDIUMTEXT().with_variant(Text, "sqlite"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(TIME_TYPE, nullable=False)

    run: Mapped[Run] = relationship(back_populates="messages")
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="message", cascade="all, delete-orphan", passive_deletes=True
    )


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        Index("idx_attachment_message", "message_id"),
        CheckConstraint("size_bytes > 0", name="ck_attachment_size"),
    )

    id: Mapped[str] = mapped_column(ID_TYPE, primary_key=True)
    message_id: Mapped[str] = mapped_column(
        ID_TYPE, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(127), nullable=False)
    size_bytes: Mapped[int] = mapped_column(
        BIGINT(unsigned=True).with_variant(Integer, "sqlite"), nullable=False
    )

    message: Mapped[Message] = relationship(back_populates="attachments")


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (CheckConstraint("seq > 0", name="ck_run_event_seq"),)

    run_id: Mapped[str] = mapped_column(
        ID_TYPE, ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(
        INTEGER(unsigned=True).with_variant(Integer, "sqlite"), primary_key=True
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIME_TYPE, nullable=False)

    run: Mapped[Run] = relationship(back_populates="events")
