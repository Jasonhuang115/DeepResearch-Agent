from __future__ import annotations

import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from agent_service.config import settings
from agent_service.producer.events import EventSeq
from agent_service.runtime.agent_runner import build_subagent_llm, run_research
from agent_service.subagents.supervisor import Supervisor

log = logging.getLogger("agent.consumer")


class Runtime:
    def __init__(self) -> None:
        self.kafka_ok = False
        self._running: dict[str, asyncio.Task] = {}
        self._cancels: dict[str, asyncio.Event] = {}
        self._done: set[str] = set()
        self.supervisor = Supervisor(llm_factory=build_subagent_llm)

    async def run(self) -> None:
        consumer = AIOKafkaConsumer(
            settings.commands_topic,
            bootstrap_servers=settings.kafka_brokers,
            group_id=settings.group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            max_partition_fetch_bytes=8 * 1024 * 1024,
        )
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_brokers,
            max_request_size=8 * 1024 * 1024,
        )
        await consumer.start()
        await producer.start()
        self.supervisor.bind_publisher(lambda payload: _publish_wake(producer, payload))
        self.supervisor.bind_events(
            lambda run_id, conversation_id, tenant_id: EventSeq(
                producer,
                run_id=run_id,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
            )
        )
        self.kafka_ok = True
        log.info("consuming %s", settings.commands_topic)
        try:
            async for msg in consumer:
                try:
                    cmd = json.loads(msg.value.decode())
                    await self._handle(cmd, producer)
                    await consumer.commit()
                except Exception:  # noqa: BLE001
                    log.exception("command failed")
                    await consumer.commit()
        finally:
            self.kafka_ok = False
            await consumer.stop()
            await producer.stop()

    async def _handle(self, cmd: dict, producer: AIOKafkaProducer) -> None:
        typ = cmd.get("type")
        run_id = cmd.get("run_id")
        if not run_id:
            return
        if typ == "cancel":
            ev = self._cancels.get(run_id)
            if ev:
                ev.set()
            conversation_id = str(cmd.get("conversation_id") or "")
            if conversation_id:
                await self.supervisor.cancel_conversation(conversation_id)
            log.info("cancel %s", run_id)
            return
        if typ != "start":
            return
        if run_id in self._running or run_id in self._done:
            log.info("skip duplicate start %s", run_id)
            return
        cancel = asyncio.Event()
        self._cancels[run_id] = cancel
        seq = EventSeq(
            producer,
            run_id=run_id,
            conversation_id=cmd.get("conversation_id") or "",
            tenant_id=cmd.get("tenant_id") or "",
        )
        task = asyncio.create_task(self._wrap(run_id, cmd, seq, cancel), name=f"run-{run_id}")
        self._running[run_id] = task

    async def _wrap(self, run_id: str, cmd: dict, seq: EventSeq, cancel: asyncio.Event) -> None:
        try:
            await run_research(cmd, seq, cancel, supervisor=self.supervisor)
        finally:
            self._running.pop(run_id, None)
            self._cancels.pop(run_id, None)
            self._done.add(run_id)


async def _publish_wake(producer: AIOKafkaProducer, payload: dict) -> None:
    conversation_id = str(payload.get("conversation_id") or "")
    await producer.send_and_wait(
        settings.wakes_topic,
        json.dumps(payload).encode(),
        key=conversation_id.encode(),
    )
