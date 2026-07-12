import json
import logging

from aiokafka import AIOKafkaProducer

from app.config import settings

logger = logging.getLogger(__name__)

_producer: AIOKafkaProducer | None = None


async def get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        )
        await _producer.start()
    return _producer


async def close_producer() -> None:
    global _producer
    if _producer:
        await _producer.stop()
        _producer = None


async def publish_event(topic: str, key: str, payload: dict) -> None:
    try:
        producer = await get_producer()
        await producer.send(
            topic=topic,
            key=key.encode(),
            value=json.dumps(payload, default=str).encode(),
        )
        logger.info("Published event to topic=%s key=%s", topic, key)
    except Exception:
        logger.exception("Failed to publish event to topic=%s key=%s", topic, key)
