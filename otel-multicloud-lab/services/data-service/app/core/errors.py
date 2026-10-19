class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class DatabaseUnavailableError(AppError):
    def __init__(self, cloud: str) -> None:
        self.cloud = cloud
        super().__init__(
            "DATABASE_UNAVAILABLE",
            f"No fue posible usar la base {cloud}",
            503,
        )


class ReplicationFailedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "REPLICATION_FAILED",
            "No fue posible replicar el evento en todas las bases",
            503,
        )


class ChaosInjectedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "CHAOS_INJECTED",
            "Se inyectó un error controlado antes de escribir",
            503,
        )


class ChaosUnauthorizedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "CHAOS_UNAUTHORIZED",
            "No autorizado",
            401,
        )
