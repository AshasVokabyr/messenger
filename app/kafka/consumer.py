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

RETRY_DELAY = 5


async def start_consumer() -> None:
    global _consumer, _consumer_task
    try:
        _consumer = AIOKafkaConsumer(
            "message_events",
            "chat_events",
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id="messenger-consumer",
            value_deserializer=lambda v: json.loads(v.decode()),
        )
        await _consumer.start()
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


async def _consume_loop() -> None:
    while True:
        try:
            async for msg in _consumer:
                await _dispatch(msg.topic, msg.value)
        except asyncio.CancelledError:
            logger.info("Consumer loop cancelled")
            break
        except KafkaConnectionError:
            logger.warning("Kafka connection lost, retrying in %ss...", RETRY_DELAY)
        except Exception:
            logger.exception("Consumer loop error")
        await asyncio.sleep(RETRY_DELAY)


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
