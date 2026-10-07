class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class OrderNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__("ORDER_NOT_FOUND", "La orden no existe", 404)


class DatabaseUnavailableError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "DATABASE_UNAVAILABLE",
            "No fue posible verificar la base de datos",
            503,
        )
