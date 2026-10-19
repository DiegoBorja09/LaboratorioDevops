import logging
import os
import re
import subprocess
import sys
import time

from app.core.logging import configure_logging

logger = logging.getLogger("app.migrations")
_CONNECTION_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://\S+")
_ATTEMPTS = 5
_TARGETS = ("GCP_DATABASE_URL", "AWS_DATABASE_URL")


def _redact(text: str) -> str:
    compact = " ".join(text.split())
    return _CONNECTION_URL.sub("***", compact)[:500]


def _upgrade(url: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["ALEMBIC_DATABASE_URL"] = url
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def _migrate(name: str, url: str) -> None:
    logger.info("Ejecutando migraciones de %s", name)
    completed = _upgrade(url)
    for attempt in range(1, _ATTEMPTS):
        if completed.returncode == 0:
            break
        logger.error("Reintento de migración %s en %s", attempt, name)
        time.sleep(2)
        completed = _upgrade(url)
    if completed.returncode != 0:
        detail = _redact(f"{completed.stdout}\n{completed.stderr}")
        logger.error("La migración de %s falló: %s", name, detail or "sin detalle")
        sys.exit(completed.returncode)
    logger.info("Migraciones de %s aplicadas", name)


def _migrations_skipped() -> bool:
    return os.environ.get("DATA_SERVICE_SKIP_MIGRATIONS", "false").strip().lower() == "true"


def main() -> None:
    configure_logging("data-service", os.environ.get("LOG_LEVEL", "INFO"))
    if _migrations_skipped():
        logger.info("Migraciones omitidas por DATA_SERVICE_SKIP_MIGRATIONS")
    else:
        for name in _TARGETS:
            url = os.environ.get(name, "").strip()
            if not url:
                logger.error("Falta la variable %s", name)
                sys.exit(1)
            _migrate(name, url)
    if len(sys.argv) > 1:
        os.execvp(sys.argv[1], sys.argv[1:])
    os.execvp(sys.executable, [sys.executable, "-m", "app.run"])


if __name__ == "__main__":
    main()
