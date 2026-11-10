from __future__ import annotations

import asyncio
import logging

from app.infra.config import settings
from app.infra.mysql import engine, session_factory
from app.infra.objects import build_object_store
from app.infra.redis import RedisStore
from app.services.cleanup import cleanup_deleted
from app.worker.executor import execute_claim
from app.worker.queue import claim_next
from app.worker.recovery import recover_expired

log = logging.getLogger(__name__)


async def run_worker() -> None:
    redis = RedisStore()
    objects = build_object_store()
    running: set[asyncio.Task[None]] = set()
    maintenance_at = 0.0
    try:
        while True:
            now = asyncio.get_running_loop().time()
            if now >= maintenance_at:
                await recover_expired(session_factory, redis)
                await cleanup_deleted(session_factory, redis, objects)
                maintenance_at = now + 5

            while len(running) < settings.worker_concurrency:
                claim = await claim_next(session_factory)
                if claim is None:
                    break
                task = asyncio.create_task(
                    execute_claim(session_factory, redis, objects, claim),
                    name=f"run-{claim.run_id}",
                )
                running.add(task)
                task.add_done_callback(running.discard)

            if running:
                await asyncio.wait(
                    running,
                    timeout=settings.worker_poll_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            else:
                await asyncio.sleep(settings.worker_poll_seconds)
    finally:
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        await redis.close()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
