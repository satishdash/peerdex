"""The installed version of a distribution, so provenance and cache keys track an upgrade."""

from functools import cache
from importlib.metadata import PackageNotFoundError, version
from typing import ClassVar


class PackageVersion:
    """Resolves a distribution's installed version, answered once per process."""

    UNKNOWN: ClassVar[str] = "unknown"

    @staticmethod
    @cache
    def of(distribution: str) -> str:
        """The version of one installed distribution.

        Args:
            distribution: The distribution name, spelled as the project requires it.

        Returns:
            The installed version, or ``unknown`` when the distribution is absent.
        """
        try:
            return version(distribution)
        except PackageNotFoundError:
            return PackageVersion.UNKNOWN
