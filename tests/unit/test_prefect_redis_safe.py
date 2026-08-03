from __future__ import annotations

import pytest
from prefect.server.utilities.messaging import BrokerModule
from prefect_redis.messaging import Consumer as RedisConsumer
from redis.exceptions import ResponseError

import digital_bast.prefect_redis_safe as broker


def test_module_satisfies_prefect_broker_contract() -> None:
    assert isinstance(broker, BrokerModule)


@pytest.mark.asyncio
async def test_missing_stream_during_trim_is_tolerated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def missing_stream(
        _consumer: RedisConsumer,
        _latest_delivered_id: str | None = None,
    ) -> None:
        message = "no such key"
        raise ResponseError(message)

    monkeypatch.setattr(RedisConsumer, "_trim_stream_if_necessary", missing_stream)
    consumer = broker.Consumer("missing-stream")

    await consumer._trim_stream_if_necessary()

    assert consumer._last_trimmed is not None


@pytest.mark.asyncio
async def test_other_redis_trim_errors_are_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def connection_error(
        _consumer: RedisConsumer,
        _latest_delivered_id: str | None = None,
    ) -> None:
        message = "WRONGTYPE Operation against a key"
        raise ResponseError(message)

    monkeypatch.setattr(RedisConsumer, "_trim_stream_if_necessary", connection_error)
    consumer = broker.Consumer("wrong-type-stream")

    with pytest.raises(ResponseError, match="WRONGTYPE"):
        await consumer._trim_stream_if_necessary()
