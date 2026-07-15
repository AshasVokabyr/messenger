from unittest.mock import AsyncMock, patch

import pytest
from aiokafka.errors import KafkaConnectionError

from app.kafka.producer import publish_event


@pytest.mark.asyncio
async def test_publish_event_retries_then_logs_critical():
    """After 3 retry attempts, logs CRITICAL and gives up."""
    mock_producer = AsyncMock()
    mock_producer.send.side_effect = KafkaConnectionError("no kafka")

    with patch("app.kafka.producer.get_producer", return_value=mock_producer):
        with patch("app.kafka.producer.logger") as mock_logger:
            await publish_event("t", "k", {"d": "v"})

            assert mock_producer.send.call_count == 4
            mock_logger.exception.assert_called_once()
            assert "CRITICAL" in mock_logger.exception.call_args[0][0]
            assert mock_logger.warning.call_count == 3


@pytest.mark.asyncio
async def test_publish_event_succeeds_on_retry():
    """Temporary Kafka unavailability — retry recovers."""
    mock_producer = AsyncMock()
    mock_producer.send.side_effect = [
        KafkaConnectionError("no kafka"),
        KafkaConnectionError("no kafka"),
        None,
    ]

    with patch("app.kafka.producer.get_producer", return_value=mock_producer):
        with patch("app.kafka.producer.logger") as mock_logger:
            await publish_event("t", "k", {"d": "v"})

            assert mock_producer.send.call_count == 3
            mock_logger.exception.assert_not_called()
