"""Per-document metadata: identity, free-form scalar attributes, sources and filters."""

import json
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from peerdex.shared.logging import get_logger

log = get_logger("shared.metadata")

type Scalar = str | int | float | bool

RESERVED_KEYS: frozenset[str] = frozenset(
    {
        "doc_id",
        "company",
        "year",
        "source_uri",
        "page_no",
        "heading_path",
        "is_table",
        "is_figure",
        "is_parent",
        "idx",
        "prompt_version",
        "extractor",
    }
)

OPAQUE_KEYS: frozenset[str] = frozenset(
    {"doc_id", "idx", "source_uri", "prompt_version", "is_parent", "extractor", "bucket_key", "url"}
)

_SIDECAR_SUFFIX: str = ".meta.json"


def _is_scalar(value: object) -> bool:
    return isinstance(value, str | int | float | bool)


def canonical_scalar(value: Scalar) -> Scalar:
    """Booleans become 1/0: LanceDB dense filters cannot express a boolean literal."""
    return int(value) if isinstance(value, bool) else value


class DocumentMetadata:
    """Identity of one indexed document plus validated free-form scalar attributes."""

    def __init__(
        self,
        company: str,
        year: int,
        source_uri: str,
        extractor: str,
        attributes: Mapping[str, Scalar] | None = None,
    ) -> None:
        self.company: str = company.strip().lower()
        self.year: int = int(year)
        self.source_uri: str = source_uri
        self.extractor: str = extractor.strip().lower()
        self.attributes: dict[str, Scalar] = {
            key: self._validated(key, value) for key, value in (attributes or {}).items()
        }

    @staticmethod
    def _validated(key: str, value: Scalar) -> Scalar:
        if key in RESERVED_KEYS:
            raise ValueError(f"attribute {key!r} shadows a reserved metadata key")
        if not _is_scalar(value):
            raise ValueError(f"attribute {key!r} must be a scalar, got {type(value).__name__}")
        return canonical_scalar(value)


class AttributeSource(ABC):
    """Port: where per-document attributes come from."""

    @abstractmethod
    def load(self, source_path: Path) -> dict[str, Scalar]:
        """Attributes for the document at ``source_path``; empty when none."""


class SidecarAttributeSource(AttributeSource):
    """Reads ``<pdf-stem>.meta.json`` next to the PDF; missing or malformed yields nothing."""

    def load(self, source_path: Path) -> dict[str, Scalar]:
        inner: Any = self._inner_object(source_path.with_suffix(_SIDECAR_SUFFIX))
        if not isinstance(inner, dict):
            return {}
        return {
            str(key): value
            for key, value in inner.items()
            if _is_scalar(value) and self._not_reserved(str(key))
        }

    @staticmethod
    def _inner_object(sidecar: Path) -> Any:
        try:
            payload: Any = json.loads(sidecar.read_text())
        except OSError, json.JSONDecodeError:
            return None
        return next(iter(payload.values()), None) if isinstance(payload, dict) else None

    @staticmethod
    def _not_reserved(key: str) -> bool:
        if key in RESERVED_KEYS:
            log.info(f"[metadata] sidecar key {key!r} is reserved, dropped")
            return False
        return True


class ExplicitAttributeSource(AttributeSource):
    """Attributes handed over explicitly, e.g. from the command line."""

    def __init__(self, attributes: Mapping[str, Scalar]) -> None:
        self._attributes: dict[str, Scalar] = dict(attributes)

    def load(self, source_path: Path) -> dict[str, Scalar]:
        return dict(self._attributes)


class CompositeAttributeSource(AttributeSource):
    """Merges several sources in order; later sources win."""

    def __init__(self, sources: Sequence[AttributeSource]) -> None:
        self._sources: list[AttributeSource] = list(sources)

    def load(self, source_path: Path) -> dict[str, Scalar]:
        merged: dict[str, Scalar] = {}
        for source in self._sources:
            merged.update(source.load(source_path))
        return merged


class AttributeFilter:
    """Equality predicate over node metadata: company always on, plus optional attributes."""

    def __init__(self, company: str, attributes: Mapping[str, Scalar] | None = None) -> None:
        self.pairs: dict[str, Scalar] = {
            "company": company.strip().lower(),
            **{key: canonical_scalar(value) for key, value in (attributes or {}).items()},
        }

    def matches(self, metadata: Mapping[str, Any]) -> bool:
        """True when every filter pair equals the node's metadata value."""
        return all(metadata.get(key) == value for key, value in self.pairs.items())


class KeyValueParser:
    """Parses repeatable ``KEY=VALUE`` CLI arguments into typed scalar attributes."""

    def parse(self, pairs: Sequence[str]) -> dict[str, Scalar]:
        """Parse every pair; ``true``/``false`` become bool, bare digits become int."""
        return dict(self._parse_one(pair) for pair in pairs)

    def _parse_one(self, pair: str) -> tuple[str, Scalar]:
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"expected KEY=VALUE, got {pair!r}")
        return key, self._coerce(raw)

    @staticmethod
    def _coerce(raw: str) -> Scalar:
        if raw.lower() in ("true", "false"):
            return raw.lower() == "true"
        return int(raw) if raw.isdigit() else raw


class MetadataVisibility:
    """Classifies node metadata keys: descriptive stay visible, opaque ids are excluded."""

    def __init__(self, opaque_keys: frozenset[str] = OPAQUE_KEYS) -> None:
        self._opaque_keys: frozenset[str] = opaque_keys

    def excluded(self, metadata: Mapping[str, Any]) -> list[str]:
        """Keys to hide from both embedding and the LLM, sorted for stability."""
        return sorted(key for key in metadata if key in self._opaque_keys)
