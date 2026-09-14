"""Extractor registry: names bound to the adapters that implement the port."""

from typing import ClassVar

from parse.contract import Extractor
from parse.docling import DoclingExtractor
from parse.docling_rs import DoclingRsExtractor
from parse.liteparse import LiteParseExtractor
from parse.odl import ODLExtractor
from parse.xberg import XbergExtractor


class ExtractorRegistry:
    """Registry and factory for the extractors a caller may request by name."""

    DEFAULT: ClassVar[str] = "docling"
    _EXTRACTORS: ClassVar[dict[str, type[Extractor]]] = {
        "docling": DoclingExtractor,
        "docling-rs": DoclingRsExtractor,
        "liteparse": LiteParseExtractor,
        "odl": ODLExtractor,
        "xberg": XbergExtractor,
    }

    @classmethod
    def register(cls, name: str, extractor: type[Extractor]) -> None:
        """Bind a name to an extractor class.

        Args:
            name: The name callers will request.
            extractor: The class to instantiate for it.
        """
        cls._EXTRACTORS[name] = extractor

    @classmethod
    def create(cls, name: str | None = None) -> Extractor:
        """Instantiate the named extractor, defaulting to docling.

        Args:
            name: The extractor to build, or None for the default.

        Returns:
            A new instance of the named extractor.

        Raises:
            ValueError: If no extractor is registered under that name.
        """
        key: str = name or cls.DEFAULT
        if key not in cls._EXTRACTORS:
            raise ValueError(f"unknown extractor '{key}'. available: {cls.available()}")
        return cls._EXTRACTORS[key]()

    @classmethod
    def available(cls) -> list[str]:
        """Every registered extractor name, sorted.

        Returns:
            The registered names in alphabetical order.
        """
        return sorted(cls._EXTRACTORS)
