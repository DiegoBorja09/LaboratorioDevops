import logging
import os
import re
import subprocess
import sys
import time

from app.core.config import get_settings
from app.core.logging import configure_logging

logger = logging.getLogger("app.migrations")
_CONNECTION_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://\S+")
_ATTEMPTS = 5


def _redact(text: str) -> str:
    compact = " ".join(text.split())
    return _CONNECTION_URL.sub("***", compact)[:500]


def _upgrade() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> None:
    settings = get_settings()
    configure_logging(settings.service_name, settings.log_level)
    logger.info("Ejecutando migraciones")
    completed = _upgrade()
    for attempt in range(1, _ATTEMPTS):
        if completed.returncode == 0:
            break
        logger.error("Reintento de migración %s", attempt)
        time.sleep(2)
        completed = _upgrade()
    if completed.returncode != 0:
        detail = _redact(f"{completed.stdout}\n{completed.stderr}")
        logger.error("La migración de base de datos falló: %s", detail or "sin detalle")
        sys.exit(completed.returncode)
    logger.info("Migraciones aplicadas")
    if len(sys.argv) > 1:
        os.execvp(sys.argv[1], sys.argv[1:])
    os.execvp(sys.executable, [sys.executable, "-m", "app.run"])


if __name__ == "__main__":
    main()
