import asyncio
import json
import logging

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError

from app.config import settings
from app.kafka.handlers import handle_chat_event, handle_message_event

logger = logging.getLogger(__name__)

_consumer: AIOKafkaConsumer | None = None
_consumer_task: asyncio.Task | None = None

MAX_RETRIES = 10
BASE_DELAY = 1
MAX_DELAY = 30

_CONSUMER_CONFIG = {
    "bootstrap_servers": settings.KAFKA_BOOTSTRAP_SERVERS,
    "group_id": "messenger-consumer",
    "value_deserializer": lambda v: json.loads(v.decode()),
    "session_timeout_ms": 30000,
    "heartbeat_interval_ms": 10000,
    "max_poll_interval_ms": 600000,
    "max_poll_records": 100,
    "enable_auto_commit": True,
    "auto_commit_interval_ms": 5000,
}


async def _create_consumer() -> AIOKafkaConsumer:
    consumer = AIOKafkaConsumer("message_events", "chat_events", **_CONSUMER_CONFIG)
    await consumer.start()
    return consumer


async def _stop_consumer_safe() -> None:
    try:
        await _consumer.stop()
    except Exception:
        pass


async def start_consumer() -> None:
    global _consumer, _consumer_task
    try:
        _consumer = await _create_consumer()
        _consumer_task = asyncio.create_task(_consume_loop())
        logger.info("Kafka consumer started")
    except Exception:
        logger.exception("Failed to start Kafka consumer")
        _consumer = None


async def _dispatch(topic: str, payload: dict) -> None:
    if topic == "message_events":
        await handle_message_event(payload)
    elif topic == "chat_events":
        await handle_chat_event(payload)


async def _run_consumer() -> None:
    async for msg in _consumer:
        await _dispatch(msg.topic, msg.value)


async def _consume_loop() -> None:
    global _consumer
    retries = 0
    while True:
        try:
            if _consumer is None:
                _consumer = await _create_consumer()
            await _run_consumer()
            raise KafkaConnectionError("Consumer stream ended")
        except asyncio.CancelledError:
            logger.info("Consumer loop cancelled")
            break
        except KafkaConnectionError:
            retries += 1
            if retries > MAX_RETRIES:
                logger.critical("Max retries (%d) exceeded, stopping consumer", MAX_RETRIES)
                break
            delay = min(BASE_DELAY * (2 ** (retries - 1)), MAX_DELAY)
            logger.warning(
                "Kafka connection lost (attempt %d/%d), retrying in %ds...",
                retries, MAX_RETRIES, delay,
            )
            await asyncio.sleep(delay)
            if _consumer is not None:
                await _stop_consumer_safe()
            _consumer = None
        except Exception:
            logger.exception("Consumer loop error")
            retries += 1
            if retries > MAX_RETRIES:
                logger.critical("Max retries (%d) exceeded, stopping consumer", MAX_RETRIES)
                break
            delay = min(BASE_DELAY * (2 ** (retries - 1)), MAX_DELAY)
            await asyncio.sleep(delay)
            if _consumer is not None:
                await _stop_consumer_safe()
            _consumer = None


async def stop_consumer() -> None:
    global _consumer, _consumer_task
    if _consumer_task is not None:
        _consumer_task.cancel()
        try:
            await _consumer_task
        except (asyncio.CancelledError, Exception):
            pass
        _consumer_task = None
    if _consumer:
        try:
            await _consumer.stop()
        except Exception:
            logger.exception("Error stopping Kafka consumer")
        _consumer = None
