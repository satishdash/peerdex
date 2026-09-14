"""Loguru-based logging. Stdout for INFO, stderr for WARN+. JSON in prod, pretty in dev."""

import sys
from typing import Any, ClassVar

from loguru import logger

from shared.settings import get_settings


class Logging:
    """Configures the sinks once per process and hands out bound loggers."""

    _CONFIGURED: ClassVar[bool] = False
    _DEV_FORMAT: ClassVar[str] = (
        "<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> - {message}"
    )

    @classmethod
    def get(cls, name: str | None = None) -> Any:
        """A logger bound to one component.

        Args:
            name: The component name, or None for the bare logger.

        Returns:
            The logger.
        """
        cls.configure()
        return logger.bind(component=name) if name else logger

    @classmethod
    def configure(cls) -> None:
        """Install the sinks, once."""
        if cls._CONFIGURED:
            return
        s = get_settings()
        logger.remove()
        cls._install(s.logging.level, prod=s.is_prod)
        cls._CONFIGURED = True

    @classmethod
    def _install(cls, level: str, *, prod: bool) -> None:
        """Add the stdout and stderr sinks for this environment.

        Args:
            level: The lowest level stdout carries.
            prod: Whether to serialise records as JSON.
        """
        if prod:
            logger.add(sys.stdout, level=level, serialize=True, filter=cls._below_warning)
            logger.add(sys.stderr, level="WARNING", serialize=True)
            return
        logger.add(
            sys.stdout,
            level=level,
            format=cls._DEV_FORMAT,
            colorize=True,
            filter=cls._below_warning,
        )
        logger.add(sys.stderr, level="WARNING", format=cls._DEV_FORMAT, colorize=True)

    @staticmethod
    def _below_warning(record: Any) -> bool:
        """Whether a record belongs on stdout rather than stderr.

        Args:
            record: The loguru record.

        Returns:
            Whether its level is below WARNING.
        """
        return bool(record["level"].no < 30)
