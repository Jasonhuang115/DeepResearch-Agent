from __future__ import annotations

import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import attachments, auth, conversations, messages, runs
from app.domain.errors import AppError
from app.infra.config import settings
from app.infra.mysql import engine, session_factory
from app.infra.objects import build_object_store
from app.infra.redis import RedisStore
from app.services.auth import decode_access_token

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.sessions = session_factory
    app.state.redis = RedisStore()
    app.state.objects = build_object_store()
    yield
    await app.state.redis.close()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Deep Research API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        if request.url.path.startswith("/v1/") and not request.url.path.startswith(
            "/v1/auth/"
        ):
            identity = request.client.host if request.client else "unknown"
            authorization = request.headers.get("authorization", "")
            if authorization.lower().startswith("bearer "):
                with suppress(AppError):
                    identity = decode_access_token(authorization[7:])
            try:
                allowed = await request.app.state.redis.rate_limit(
                    "api", identity, 300, 60
                )
            except Exception:
                allowed = True
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "rate_limited",
                            "message": "Too many requests.",
                        }
                    },
                )
        return await call_next(request)

    @app.exception_handler(AppError)
    async def app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "details": exc.errors(),
                }
            },
        )

    app.include_router(auth.router)
    app.include_router(conversations.router)
    app.include_router(messages.router)
    app.include_router(attachments.router)
    app.include_router(runs.router)

    @app.get("/health/live")
    async def live() -> dict:
        return {"ok": True}

    @app.get("/health/ready")
    async def ready(request: Request) -> JSONResponse:
        mysql_ok = False
        redis_ok = False
        objects_ok = False
        try:
            async with session_factory() as session:
                await session.execute(text("SELECT 1"))
            mysql_ok = True
        except Exception:
            log.warning("MySQL readiness failed", exc_info=True)
        try:
            redis_ok = await request.app.state.redis.ping()
        except Exception:
            log.warning("Redis readiness failed", exc_info=True)
        try:
            await request.app.state.objects.exists("__health__")
            objects_ok = True
        except Exception:
            log.warning("Object storage readiness failed", exc_info=True)
        ready_ok = mysql_ok and redis_ok and objects_ok
        return JSONResponse(
            status_code=200 if ready_ok else 503,
            content={
                "ok": ready_ok,
                "mysql": mysql_ok,
                "redis": redis_ok,
                "objects": objects_ok,
            },
        )

    return app


app = create_app()
