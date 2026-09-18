class TicketForgeError(Exception):
    def __init__(self, code: str, message: str, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


class ConfigError(Exception):
    pass
