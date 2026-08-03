from typing import override


class AuthenticationUnavailableError(Exception):
    def __init__(self, service: str = "NocoDB") -> None:
        super().__init__(service)
        self.service: str = service

    @override
    def __str__(self) -> str:
        return f"{self.service} authentication is unavailable"


class SessionUnavailableError(Exception):
    def __init__(self, operation: str) -> None:
        super().__init__(operation)
        self.operation: str = operation

    @override
    def __str__(self) -> str:
        return f"session storage failed during {self.operation}"


class WebBackendUnavailableError(Exception):
    def __init__(self, operation: str) -> None:
        super().__init__(operation)
        self.operation: str = operation

    @override
    def __str__(self) -> str:
        return f"web backend failed during {self.operation}"
