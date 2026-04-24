"""Loguru-based logging. Stdout for INFO, stderr for WARN+. JSON in prod, pretty in dev."""

import sys

from loguru import logger

from peerdex.shared.settings import get_settings

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    s = get_settings()
    logger.remove()
    if s.is_prod:
        logger.add(sys.stdout, level=s.logging.level, serialize=True,
                   filter=lambda r: r["level"].no < 30)
        logger.add(sys.stderr, level="WARNING", serialize=True)
    else:
        fmt = ("<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | "
               "<cyan>{name}</cyan>:<cyan>{line}</cyan> - {message}")
        logger.add(sys.stdout, level=s.logging.level, format=fmt, colorize=True,
                   filter=lambda r: r["level"].no < 30)
        logger.add(sys.stderr, level="WARNING", format=fmt, colorize=True)
    _configured = True


def get_logger(name: str | None = None):
    configure_logging()
    return logger.bind(component=name) if name else logger
