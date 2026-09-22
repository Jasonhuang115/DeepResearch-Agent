from __future__ import annotations

from agent_service.envfile import load_repo_env

# Settings reads the environment when its module is imported.
load_repo_env()

import asyncio
import logging

import uvicorn

from agent_service.api.app import create_app
from agent_service.config import settings
from agent_service.consumer.commands import Runtime


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    runtime = Runtime()
    app = create_app(runtime)
    host, _, port = settings.http_addr.rpartition(":")
    config = uvicorn.Config(app, host=host or "127.0.0.1", port=int(port or "8001"), log_level="info")
    server = uvicorn.Server(config)
    await asyncio.gather(server.serve(), runtime.run())


if __name__ == "__main__":
    asyncio.run(main())
