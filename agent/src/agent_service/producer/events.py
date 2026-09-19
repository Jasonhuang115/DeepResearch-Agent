from __future__ import annotations

import json

from aiokafka import AIOKafkaProducer

from agent_service.config import settings
from agent_service.events import envelope


class EventSeq:
    def __init__(
        self,
        producer: AIOKafkaProducer,
        *,
        run_id: str,
        conversation_id: str,
        tenant_id: str,
    ) -> None:
        self.producer = producer
        self.run_id = run_id
        self.conversation_id = conversation_id
        self.tenant_id = tenant_id
        self.seq = 0

    async def emit(self, typ: str, payload: dict | None = None) -> None:
        self.seq += 1
        body = envelope(
            run_id=self.run_id,
            conversation_id=self.conversation_id,
            tenant_id=self.tenant_id,
            seq=self.seq,
            typ=typ,
            payload=payload,
        )
        await self.producer.send_and_wait(
            settings.events_topic,
            json.dumps(body).encode(),
            key=self.conversation_id.encode(),
        )
