from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def configure_logging(
    verbose: bool = False,
    *,
    console: bool = True,
    log_file: Path | None = None,
) -> None:
    """Konfiguriert Loguru ohne ungefragt lokale Dateien anzulegen."""
    logger.remove()

    if console:
        console_level = "DEBUG" if verbose else "INFO"
        console_format = (
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
        )
        logger.add(
            sys.stderr,
            level=console_level,
            format=console_format,
            backtrace=False,
            diagnose=False,
        )

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            str(log_file),
            level="DEBUG",
            rotation="5 MB",
            retention="10 days",
            format=(
                "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
                "{name}:{function}:{line} - {message}"
            ),
            backtrace=True,
            diagnose=False,
        )
