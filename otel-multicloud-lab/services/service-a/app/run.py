import uvicorn

from app.core.config import get_settings
from app.core.logging import build_uvicorn_log_config


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8080,
        access_log=False,
        log_config=build_uvicorn_log_config(settings.service_name, settings.log_level),
    )


if __name__ == "__main__":
    main()
