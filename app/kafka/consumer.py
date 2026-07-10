import json
import logging

from aiokafka import AIOKafkaConsumer

from app.config import settings

logger = logging.getLogger(__name__)

_consumer: AIOKafkaConsumer | None = None


async def start_consumer() -> None:
    global _consumer
    _consumer = AIOKafkaConsumer(
        "message_events",
        "chat_events",
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="messenger-consumer",
        value_deserializer=lambda v: json.loads(v.decode()),
    )
    await _consumer.start()


async def consume_events() -> None:
    if _consumer is None:
        return
    async for msg in _consumer:
        logger.info("Received event topic=%s key=%s value=%s", msg.topic, msg.key, msg.value)


async def stop_consumer() -> None:
    global _consumer
    if _consumer:
        await _consumer.stop()
        _consumer = None
