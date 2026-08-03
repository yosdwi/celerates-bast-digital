from dataclasses import dataclass
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True, slots=True)
class RedisEndpoint:
    host: str
    port: int
    database: int
    username: str | None
    password: str | None
    ssl: bool


def parse_redis_url(url: str) -> RedisEndpoint:
    parsed = urlsplit(url)
    if parsed.scheme not in {"redis", "rediss"} or parsed.hostname is None:
        msg = "Redis URL must use redis:// or rediss:// with a hostname"
        raise ValueError(msg)
    database_text = parsed.path.removeprefix("/")
    try:
        database = int(database_text) if database_text else 0
    except ValueError as error:
        msg = "Redis URL database path must be an integer"
        raise ValueError(msg) from error
    return RedisEndpoint(
        host=parsed.hostname,
        port=parsed.port or 6379,
        database=database,
        username=unquote(parsed.username) if parsed.username is not None else None,
        password=unquote(parsed.password) if parsed.password is not None else None,
        ssl=parsed.scheme == "rediss",
    )
