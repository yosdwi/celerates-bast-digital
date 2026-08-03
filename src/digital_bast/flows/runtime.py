from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from importlib import import_module
from typing import TYPE_CHECKING, override

from digital_bast.flows.contracts import RunContext, RunContextFactory

if TYPE_CHECKING:
    from collections.abc import Generator


class RunContextUnavailableError(RuntimeError):
    @override
    def __str__(self) -> str:
        return "run context is not configured"


class InvalidRunContextFactoryError(RuntimeError):
    def __init__(self, value: str) -> None:
        super().__init__(value)
        self.value: str = value

    @override
    def __str__(self) -> str:
        return f"invalid run context factory {self.value!r}; expected module:callable"


_factory: ContextVar[RunContextFactory | None] = ContextVar(
    "digital_bast_run_context",
    default=None,
)


def get_run_context() -> RunContext:
    factory = _factory.get()
    if factory is not None:
        return factory()
    path = os.environ.get("DIGITAL_BAST_RUN_CONTEXT_FACTORY")
    if path is None:
        raise RunContextUnavailableError
    module_name, separator, attribute = path.partition(":")
    if not separator or not module_name or not attribute:
        raise InvalidRunContextFactoryError(path)
    candidate = getattr(import_module(module_name), attribute, None)
    if not callable(candidate):
        raise InvalidRunContextFactoryError(path)
    context = candidate()
    if not isinstance(context, RunContext):
        raise InvalidRunContextFactoryError(path)
    return context


@contextmanager
def use_run_context(factory: RunContextFactory) -> Generator[None]:
    token = _factory.set(factory)
    try:
        yield
    finally:
        _factory.reset(token)
