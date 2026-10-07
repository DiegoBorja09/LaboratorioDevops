class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ServiceUnavailableError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "SERVICE_B_UNAVAILABLE",
            "No fue posible comunicarse con service-b",
            502,
        )


class ServiceTimeoutError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "SERVICE_B_TIMEOUT",
            "service-b no respondió dentro del tiempo esperado",
            504,
        )
