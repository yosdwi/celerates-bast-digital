from datetime import timedelta
from typing import AbstractAsyncContextManager, TypedDict

class Cache: ...
class Publisher: ...

class EphemeralSubscriptionParameters(TypedDict):
    topic: str
    name: str
    starting_message_id: str
    use_consumer_group: bool

class Consumer:
    _last_trimmed: float | None

    def __init__(
        self,
        topic: str,
        name: str | None = ...,
        group: str | None = ...,
        block: timedelta | None = ...,
        min_idle_time: timedelta | None = ...,
        should_process_pending_messages: bool | None = ...,
        starting_message_id: str | None = ...,
        automatically_acknowledge: bool | None = ...,
        max_retries: int | None = ...,
        trim_every: timedelta | None = ...,
        read_batch_size: int | None = ...,
        use_consumer_group: bool = ...,
    ) -> None: ...
    async def _trim_stream_if_necessary(
        self,
        latest_delivered_id: str | None = ...,
    ) -> None: ...

def ephemeral_subscription(
    topic: str,
    source: str | None = ...,
    group: str | None = ...,
) -> AbstractAsyncContextManager[EphemeralSubscriptionParameters]: ...
def break_topic() -> AbstractAsyncContextManager[None]: ...
