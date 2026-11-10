from __future__ import annotations

import hashlib
import json
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from app.infra.config import settings


class RedisStore:
    def __init__(self, client: Redis | None = None) -> None:
        self.client = client or Redis.from_url(settings.redis_url, decode_responses=True)

    async def ping(self) -> bool:
        return bool(await self.client.ping())

    async def close(self) -> None:
        await self.client.aclose()

    async def set_refresh(self, token: str, user_id: str) -> None:
        await self.client.set(
            self.refresh_key(token), user_id, ex=settings.refresh_token_seconds
        )

    async def get_refresh(self, token: str) -> str | None:
        value = await self.client.get(self.refresh_key(token))
        return str(value) if value else None

    async def delete_refresh(self, token: str) -> None:
        await self.client.delete(self.refresh_key(token))

    async def rotate_refresh(self, old_token: str, new_token: str) -> str | None:
        script = """
        local user_id = redis.call('GET', KEYS[1])
        if not user_id then
            return false
        end
        redis.call('DEL', KEYS[1])
        redis.call('SET', KEYS[2], user_id, 'EX', ARGV[1])
        return user_id
        """
        value = await self.client.eval(
            script,
            2,
            self.refresh_key(old_token),
            self.refresh_key(new_token),
            settings.refresh_token_seconds,
        )
        return str(value) if value else None

    async def publish_event(self, run_id: str, event: dict[str, Any]) -> None:
        await self.client.publish(
            f"run:{run_id}:events", json.dumps(event, ensure_ascii=False, default=str)
        )

    async def publish_cancel(self, run_id: str) -> None:
        await self.client.publish(f"run:{run_id}:control", json.dumps({"type": "cancel"}))

    async def subscribe_events(self, run_id: str) -> PubSub:
        pubsub = self.client.pubsub()
        await pubsub.subscribe(f"run:{run_id}:events")
        return pubsub

    async def subscribe_control(self, run_id: str) -> PubSub:
        pubsub = self.client.pubsub()
        await pubsub.subscribe(f"run:{run_id}:control")
        return pubsub

    async def sandbox_get(self, user_id: str, conversation_id: str) -> str | None:
        value = await self.client.get(f"sandbox:{user_id}:{conversation_id}")
        return str(value) if value else None

    async def sandbox_set(self, user_id: str, conversation_id: str, sandbox_id: str) -> None:
        await self.client.set(
            f"sandbox:{user_id}:{conversation_id}",
            sandbox_id,
            ex=settings.sandbox_ttl_seconds,
        )

    async def sandbox_delete(self, user_id: str, conversation_id: str) -> None:
        await self.client.delete(f"sandbox:{user_id}:{conversation_id}")

    async def rate_limit(self, scope: str, identity: str, limit: int, seconds: int) -> bool:
        key = f"rate:{scope}:{identity}"
        count = await self.client.incr(key)
        if count == 1:
            await self.client.expire(key, seconds)
        return int(count) <= limit

    @staticmethod
    def refresh_key(token: str) -> str:
        digest = hashlib.sha256(token.encode()).hexdigest()
        return f"auth:refresh:{digest}"
