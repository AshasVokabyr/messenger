import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer

from app.config import settings

logger = logging.getLogger(__name__)

_consumer: AIOKafkaConsumer | None = None
_consumer_task: asyncio.Task | None = None


async def start_consumer() -> None:
    global _consumer, _consumer_task
    _consumer = AIOKafkaConsumer(
        "message_events",
        "chat_events",
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="messenger-consumer",
        value_deserializer=lambda v: json.loads(v.decode()),
    )
    await _consumer.start()
    _consumer_task = asyncio.create_task(_consume_loop())


async def _consume_loop() -> None:
    if _consumer is None:
        return
    try:
        async for msg in _consumer:
            logger.info("Received event topic=%s key=%s value=%s", msg.topic, msg.key, msg.value)
    except Exception:
        logger.exception("Consumer loop error")


async def stop_consumer() -> None:
    global _consumer, _consumer_task
    if _consumer_task is not None:
        _consumer_task.cancel()
        _consumer_task = None
    if _consumer:
        await _consumer.stop()
        _consumer = None
