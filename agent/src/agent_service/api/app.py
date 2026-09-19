from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from agent_service.consumer.commands import Runtime


def create_app(runtime: Runtime) -> FastAPI:
    app = FastAPI(title="research-agent", docs_url=None, redoc_url=None)

    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz() -> str:
        return "ok"

    @app.get("/readyz")
    async def readyz() -> dict:
        if not runtime.kafka_ok:
            return {"ok": False}
        return {"ok": True}

    return app
