from digital_bast.infrastructure.sessions import RedisSessionStore


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}

    def set(self, name: str, value: str, *, ex: int) -> bool:
        self.values[name] = value
        self.expiries[name] = ex
        return True

    def getex(self, name: str, *, ex: int) -> str | None:
        value = self.values.get(name)
        if value is not None:
            self.expiries[name] = ex
        return value

    def delete(self, *names: str) -> int:
        deleted = 0
        for name in names:
            if name in self.values:
                deleted += 1
                del self.values[name]
                del self.expiries[name]
        return deleted


def test_session_round_trip_refreshes_expiry() -> None:
    backend = FakeRedis()
    store = RedisSessionStore(backend, ttl_seconds=300)

    created = store.create("user-1", ("operator",))
    loaded = store.get(created.session_id)

    assert loaded == created
    assert backend.expiries[f"bast:session:{created.session_id}"] == 300


def test_expired_session_is_absent() -> None:
    backend = FakeRedis()
    store = RedisSessionStore(backend, ttl_seconds=300)
    created = store.create("user-1", ("operator",))
    backend.delete(f"bast:session:{created.session_id}")

    assert store.get(created.session_id) is None
