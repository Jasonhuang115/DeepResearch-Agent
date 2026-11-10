from __future__ import annotations

import secrets
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import AppError, unauthorized
from app.domain.models import User
from app.domain.util import new_id, utc_now
from app.infra.config import settings
from app.infra.redis import RedisStore

_passwords = PasswordHasher()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    return _passwords.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _passwords.verify(password_hash, password)
    except (InvalidHashError, VerifyMismatchError):
        return False


def create_access_token(user_id: str) -> str:
    now = utc_now()
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(seconds=settings.access_token_seconds),
        "type": "access",
    }
    return str(jwt.encode(payload, settings.jwt_secret, algorithm="HS256"))


def decode_access_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise unauthorized("Invalid or expired access token.") from exc
    if payload.get("type") != "access" or not payload.get("sub"):
        raise unauthorized("Invalid access token.")
    return str(payload["sub"])


async def register(session: AsyncSession, email: str, password: str) -> User:
    normalized = normalize_email(email)
    existing = await session.scalar(select(User.id).where(User.email == normalized))
    if existing:
        raise AppError(409, "email_exists", "This email is already registered.")
    user = User(
        id=new_id(),
        email=normalized,
        password_hash=hash_password(password),
        created_at=utc_now(),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AppError(409, "email_exists", "This email is already registered.") from exc
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    normalized = normalize_email(email)
    user = await session.scalar(select(User).where(User.email == normalized))
    if user is None or not verify_password(user.password_hash, password):
        raise unauthorized("Invalid email or password.")
    return user


async def issue_refresh(redis: RedisStore, user_id: str) -> str:
    token = secrets.token_urlsafe(48)
    await redis.set_refresh(token, user_id)
    return token


async def rotate_refresh(redis: RedisStore, old_token: str) -> tuple[str, str]:
    new_token = secrets.token_urlsafe(48)
    user_id = await redis.rotate_refresh(old_token, new_token)
    if not user_id:
        raise unauthorized("Invalid or expired refresh token.")
    return user_id, new_token
