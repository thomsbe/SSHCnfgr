from __future__ import annotations

import sys

from loguru import logger

from .paths import LOG_PATH, ensure_app_dir


def configure_logging(verbose: bool = False) -> None:
    ensure_app_dir()
    logger.remove()

    console_level = "DEBUG" if verbose else "INFO"
    logger.add(
        sys.stderr,
        level=console_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        backtrace=False,
        diagnose=False,
    )

    logger.add(
        str(LOG_PATH),
        level="DEBUG",
        rotation="5 MB",
        retention="10 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        backtrace=True,
        diagnose=False,
    )
