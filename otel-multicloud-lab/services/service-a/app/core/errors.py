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


class DataServiceError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "DATA_SERVICE_UNAVAILABLE",
            "La orden se creó en service-b, pero no fue posible replicar el evento de auditoría",
            502,
        )


class DataServiceTimeoutError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "DATA_SERVICE_TIMEOUT",
            "La orden se creó en service-b, pero data-service no respondió a tiempo",
            504,
        )
