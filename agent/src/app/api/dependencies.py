from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import unauthorized
from app.domain.models import User
from app.infra.mysql import get_session
from app.infra.objects import ObjectStore
from app.infra.redis import RedisStore
from app.services.auth import decode_access_token

bearer = HTTPBearer(auto_error=False)
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_redis(request: Request) -> RedisStore:
    return request.app.state.redis


def get_objects(request: Request) -> ObjectStore:
    return request.app.state.objects


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: SessionDep,
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    user_id = decode_access_token(credentials.credentials)
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise unauthorized()
    return user


CurrentUser = Annotated[User, Depends(current_user)]
RedisDep = Annotated[RedisStore, Depends(get_redis)]
ObjectsDep = Annotated[ObjectStore, Depends(get_objects)]
