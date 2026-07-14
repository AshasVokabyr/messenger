import asyncio
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
    delays = [1, 2, 4]
    for attempt in range(len(delays) + 1):
        try:
            producer = await get_producer()
            await producer.send(
                topic=topic,
                key=key.encode(),
                value=json.dumps(payload, default=str).encode(),
            )
            logger.info("Published event to topic=%s key=%s", topic, key)
            return
        except Exception:
            if attempt < len(delays):
                logger.warning(
                    "Failed to publish to topic=%s key=%s (attempt %d/%d)",
                    topic, key, attempt + 1, len(delays) + 1, exc_info=True,
                )
                await asyncio.sleep(delays[attempt])
            else:
                logger.exception(
                    "CRITICAL: Lost event topic=%s key=%s after %d attempts",
                    topic, key, len(delays) + 1,
                )
