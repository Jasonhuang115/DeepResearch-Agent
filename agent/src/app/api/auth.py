from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.api.dependencies import CurrentUser, RedisDep, SessionDep
from app.domain.errors import AppError
from app.domain.models import User
from app.domain.schemas import AuthInput, TokenView, UserView
from app.infra.config import settings
from app.services import auth as service

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _set_refresh(response: Response, token: str) -> None:
    response.set_cookie(
        settings.refresh_cookie_name,
        token,
        max_age=settings.refresh_token_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/v1/auth",
    )


def _token_view(user: object) -> dict:
    return TokenView(
        access_token=service.create_access_token(user.id),
        expires_in=settings.access_token_seconds,
        user=UserView.model_validate(user),
    ).model_dump(mode="json")


@router.post("/register", status_code=201)
async def register(
    body: AuthInput, response: Response, session: SessionDep, redis: RedisDep
) -> dict:
    user = await service.register(session, str(body.email), body.password)
    refresh = await service.issue_refresh(redis, user.id)
    _set_refresh(response, refresh)
    return {"data": _token_view(user)}


@router.post("/login")
async def login(
    body: AuthInput,
    request: Request,
    response: Response,
    session: SessionDep,
    redis: RedisDep,
) -> dict:
    identity = request.client.host if request.client else "unknown"
    if not await redis.rate_limit("login", identity, 20, 900):
        raise AppError(429, "rate_limited", "Too many login attempts.")
    user = await service.authenticate(session, str(body.email), body.password)
    refresh = await service.issue_refresh(redis, user.id)
    _set_refresh(response, refresh)
    return {"data": _token_view(user)}


@router.post("/refresh")
async def refresh(
    request: Request, response: Response, session: SessionDep, redis: RedisDep
) -> dict:
    old = request.cookies.get(settings.refresh_cookie_name)
    if not old:
        raise AppError(401, "unauthorized", "Refresh token is missing.")
    user_id, new = await service.rotate_refresh(redis, old)
    user = await session.get(User, user_id)
    if user is None:
        await redis.delete_refresh(new)
        raise AppError(401, "unauthorized", "User no longer exists.")
    _set_refresh(response, new)
    return {"data": _token_view(user)}


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, redis: RedisDep) -> Response:
    token = request.cookies.get(settings.refresh_cookie_name)
    if token:
        await redis.delete_refresh(token)
    response.delete_cookie(settings.refresh_cookie_name, path="/v1/auth")
    response.status_code = 204
    return response


@router.get("/me")
async def me(user: CurrentUser) -> dict:
    return {"data": UserView.model_validate(user).model_dump(mode="json")}
