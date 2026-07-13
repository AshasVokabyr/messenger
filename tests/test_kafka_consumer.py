import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiokafka.errors import KafkaConnectionError


class MockMessage:
    def __init__(self, topic, value, key=None):
        self.topic = topic
        self.value = value
        self.key = key


class MockConsumer:
    def __init__(self, items, exc_stop=None):
        self._items = items
        self._exc_stop = exc_stop
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._exc_stop is not None and self._idx >= len(self._items):
            raise self._exc_stop
        if self._idx >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._idx]
        self._idx += 1
        return item


class TestDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_message_event(self):
        from app.kafka.consumer import _dispatch

        payload = {"id": "msg-1", "chat_id": "chat-1", "content": "hello"}

        with patch("app.kafka.consumer.handle_message_event", new_callable=AsyncMock) as mock:
            await _dispatch("message_events", payload)

        mock.assert_awaited_once_with(payload)

    @pytest.mark.asyncio
    async def test_dispatch_chat_event(self):
        from app.kafka.consumer import _dispatch

        payload = {"type": "participants_added", "chat_id": "chat-1"}

        with patch("app.kafka.consumer.handle_chat_event", new_callable=AsyncMock) as mock:
            await _dispatch("chat_events", payload)

        mock.assert_awaited_once_with(payload)


class TestConsumeLoop:
    @pytest.mark.asyncio
    async def test_consume_loop_dispatches_messages(self):
        from app.kafka.consumer import _consume_loop

        msg1 = MockMessage("message_events", {"content": "hello"})
        msg2 = MockMessage("chat_events", {"type": "participant_removed"})
        consumer = MockConsumer([msg1, msg2])

        with (
            patch("app.kafka.consumer._consumer", consumer),
            patch("app.kafka.consumer._dispatch", new_callable=AsyncMock) as dispatch_mock,
            patch("app.kafka.consumer.RETRY_DELAY", 0.05),
        ):
            task = asyncio.create_task(_consume_loop())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            assert dispatch_mock.await_count == 2
            dispatch_mock.assert_any_await("message_events", {"content": "hello"})
            dispatch_mock.assert_any_await("chat_events", {"type": "participant_removed"})

    @pytest.mark.asyncio
    async def test_consume_loop_reconnects_on_kafka_error(self):
        from app.kafka.consumer import _consume_loop

        consumer = MockConsumer([], exc_stop=KafkaConnectionError("test error"))

        with (
            patch("app.kafka.consumer._consumer", consumer),
            patch("app.kafka.consumer.RETRY_DELAY", 0.05),
        ):
            task = asyncio.create_task(_consume_loop())
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_consume_loop_cancelled_gracefully(self):
        from app.kafka.consumer import _consume_loop

        consumer = MockConsumer([], exc_stop=asyncio.CancelledError())

        with patch("app.kafka.consumer._consumer", consumer):
            result = await _consume_loop()

        assert result is None


class TestStartConsumer:
    @pytest.mark.asyncio
    async def test_start_consumer_failure_does_not_crash(self):
        from app.kafka.consumer import start_consumer, _consumer

        with (
            patch("app.kafka.consumer.AIOKafkaConsumer") as consumer_cls,
            patch("app.kafka.consumer.logger") as mock_logger,
        ):
            consumer_instance = AsyncMock()
            consumer_instance.start.side_effect = KafkaConnectionError("no kafka")
            consumer_cls.return_value = consumer_instance

            await start_consumer()

            assert _consumer is None
            mock_logger.exception.assert_called_once()
