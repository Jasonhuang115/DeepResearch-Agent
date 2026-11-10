from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.domain.enums import MessageRole, RunStatus
from app.domain.models import Base, Conversation, Message, Run, User
from app.domain.util import new_id, utc_now
from app.services.auth import authenticate, create_access_token, decode_access_token, register
from app.services.events import EventWriter, StaleWorkerError
from app.worker.queue import claim_next
from app.worker.recovery import recover_expired


class FakeRedis:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish_event(self, run_id: str, event: dict) -> None:
        assert run_id == event["run_id"]
        self.events.append(event)


@pytest.fixture
async def sessions():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def seed_run(sessions, *, status: str = RunStatus.QUEUED, attempts: int = 0) -> Run:
    now = utc_now()
    async with sessions() as session, session.begin():
        user = User(
            id=new_id(),
            email=f"{new_id()}@example.com",
            password_hash="hash",
            created_at=now,
        )
        conversation = Conversation(
            id=new_id(),
            user_id=user.id,
            title="test",
            created_at=now,
            updated_at=now,
        )
        run = Run(
            id=new_id(),
            conversation_id=conversation.id,
            idempotency_key=new_id(),
            status=status,
            attempt_count=attempts,
            lease_expires_at=(now - timedelta(seconds=1)) if status == RunStatus.RUNNING else None,
            created_at=now,
        )
        message = Message(
            id=new_id(),
            run_id=run.id,
            role=MessageRole.USER,
            content="question",
            created_at=now,
        )
        session.add_all((user, conversation, run, message))
    return run


def test_schema_has_exactly_six_business_tables() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "conversations",
        "runs",
        "messages",
        "attachments",
        "run_events",
    }


@pytest.mark.asyncio
async def test_auth_hashes_password_and_issues_access_token(sessions) -> None:
    async with sessions() as session:
        user = await register(session, " USER@Example.com ", "long-enough-password")
        assert user.email == "user@example.com"
        assert user.password_hash != "long-enough-password"
        authenticated = await authenticate(session, user.email, "long-enough-password")
        assert decode_access_token(create_access_token(authenticated.id)) == authenticated.id


@pytest.mark.asyncio
async def test_claim_and_fencing(sessions) -> None:
    run = await seed_run(sessions)
    claim = await claim_next(sessions)
    assert claim is not None
    assert claim.run_id == run.id
    assert claim.attempt_count == 1

    redis = FakeRedis()
    writer = EventWriter(sessions, redis, run.id, 1)
    event = await writer.emit("run.started", {})
    assert event["seq"] == 1

    stale = EventWriter(sessions, redis, run.id, 0)
    with pytest.raises(StaleWorkerError):
        await stale.emit("run.progress", {})


@pytest.mark.asyncio
async def test_expired_run_recovers_once_then_fails(sessions) -> None:
    run = await seed_run(sessions, status=RunStatus.RUNNING, attempts=1)
    redis = FakeRedis()
    assert await recover_expired(sessions, redis) == 1
    async with sessions() as session:
        recovered = await session.get(Run, run.id)
        assert recovered is not None
        assert recovered.status == RunStatus.QUEUED

    claim = await claim_next(sessions)
    assert claim is not None
    async with sessions() as session, session.begin():
        claimed = await session.get(Run, run.id)
        assert claimed is not None
        claimed.lease_expires_at = utc_now() - timedelta(seconds=1)

    assert await recover_expired(sessions, redis) == 1
    async with sessions() as session:
        failed = await session.get(Run, run.id)
        assert failed is not None
        assert failed.status == RunStatus.FAILED
    assert [event["type"] for event in redis.events][-2:] == ["error", "run.finished"]
