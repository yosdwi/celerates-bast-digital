from typing import override


class InfrastructureError(Exception):
    def __init__(self, service: str, operation: str) -> None:
        super().__init__(service, operation)
        self.service: str = service
        self.operation: str = operation

    @override
    def __str__(self) -> str:
        return f"{self.service} {self.operation} failed"


class AuthenticationError(InfrastructureError):
    pass


class UpstreamTimeoutError(InfrastructureError):
    pass


class UpstreamUnavailableError(InfrastructureError):
    pass


class InvalidIdentifierError(InfrastructureError):
    def __init__(self, service: str, operation: str, identifier: str) -> None:
        super().__init__(service, operation)
        self.identifier: str = identifier


class LockConflictError(InfrastructureError):
    def __init__(self, service: str, operation: str, record_key: str) -> None:
        super().__init__(service, operation)
        self.record_key: str = record_key
