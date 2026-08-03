from typing import AbstractAsyncContextManager, Any

class Cache: ...

class Publisher: ...

class Consumer:
    _last_trimmed: float | None

    def __init__(
        self,
        topic: str,
        name: str | None = ...,
        group: str | None = ...,
        use_consumer_group: bool = ...,
        **kwargs: Any,
    ) -> None: ...

    async def _trim_stream_if_necessary(
        self,
        latest_delivered_id: str | None = ...,
    ) -> None: ...

def ephemeral_subscription(
    topic: str,
    source: str | None = ...,
    group: str | None = ...,
) -> AbstractAsyncContextManager[dict[str, Any]]: ...

def break_topic() -> AbstractAsyncContextManager[None]: ...
