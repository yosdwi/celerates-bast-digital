from __future__ import annotations

import time

from prefect_redis.messaging import Cache, Publisher, break_topic, ephemeral_subscription
from prefect_redis.messaging import Consumer as RedisConsumer
from redis.exceptions import ResponseError


class Consumer(RedisConsumer):
    async def _trim_stream_if_necessary(
        self,
        latest_delivered_id: str | None = None,
    ) -> None:
        try:
            await super()._trim_stream_if_necessary(latest_delivered_id)
        except ResponseError as exc:
            if "no such key" not in str(exc).lower():
                raise
            self._last_trimmed = time.monotonic()


__all__ = [
    "Cache",
    "Consumer",
    "Publisher",
    "break_topic",
    "ephemeral_subscription",
]
