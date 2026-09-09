"""Per-document metadata: identity, free-form scalar attributes, sources and filters."""

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TypeIs

from peerdex.shared.logging import get_logger

log = get_logger("shared.metadata")

type Scalar = str | int | float | bool
type Scalars = Scalar | Sequence[Scalar]

RESERVED_KEYS: frozenset[str] = frozenset(
    {
        "doc_id",
        "source_doc_id",
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
    {
        "doc_id",
        "source_doc_id",
        "idx",
        "source_uri",
        "prompt_version",
        "is_parent",
        "extractor",
        "bucket_key",
        "url",
    }
)

_SIDECAR_SUFFIX: str = ".meta.json"
_ALTERNATIVE_SEPARATOR: re.Pattern[str] = re.compile(r"(?<!\\),")


def _is_scalar(value: object) -> TypeIs[Scalar]:
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
    """Node-metadata predicate: AND across keys, OR within a key, company always on."""

    def __init__(self, company: str, attributes: Mapping[str, Scalars] | None = None) -> None:
        self.pairs: dict[str, tuple[Scalar, ...]] = {
            "company": (company.strip().lower(),),
            **{key: self._admitted(key, values) for key, values in (attributes or {}).items()},
        }

    def matches(self, metadata: Mapping[str, Any]) -> bool:
        """True when the node's value for every filter key is one of that key's admitted values."""
        return all(metadata.get(key) in values for key, values in self.pairs.items())

    @staticmethod
    def _admitted(key: str, values: Scalars) -> tuple[Scalar, ...]:
        canonical: tuple[Scalar, ...] = tuple(
            canonical_scalar(value) for value in ((values,) if _is_scalar(values) else values)
        )
        if len({type(value) for value in canonical}) != 1:
            raise ValueError(
                f"filter {key!r} needs one or more values of a single type, got {canonical!r}"
            )
        return canonical


class ValueParser[T](ABC):
    """Strategy: how the text right of ``=`` becomes a typed value."""

    @abstractmethod
    def parse(self, raw: str) -> T:
        """Typed value for ``raw``."""


class ScalarValueParser(ValueParser[Scalar]):
    """``true``/``false`` become bool, bare digits become int, anything else stays text."""

    def parse(self, raw: str) -> Scalar:
        if raw.lower() in ("true", "false"):
            return raw.lower() == "true"
        return int(raw) if raw.isdigit() else raw


class ScalarSetValueParser(ValueParser[tuple[Scalar, ...]]):
    """Comma-separated alternatives, ``\\,`` escapes a comma; mixed types all fall back to text."""

    def __init__(self) -> None:
        self._member: ScalarValueParser = ScalarValueParser()

    def parse(self, raw: str) -> tuple[Scalar, ...]:
        parts: list[str] = [part.replace("\\,", ",") for part in _ALTERNATIVE_SEPARATOR.split(raw)]
        typed: tuple[Scalar, ...] = tuple(self._member.parse(part) for part in parts)
        return typed if len({type(value) for value in typed}) == 1 else tuple(parts)


class KeyValueParser[T]:
    """Parses repeatable ``KEY=VALUE`` CLI arguments; a ``ValueParser`` types the value side."""

    def __init__(self, values: ValueParser[T]) -> None:
        self._values: ValueParser[T] = values

    def parse(self, pairs: Sequence[str]) -> dict[str, T]:
        """Parse every pair; a key may appear only once."""
        parsed: dict[str, T] = {}
        for pair in pairs:
            key, value = self._parse_one(pair)
            if key in parsed:
                raise ValueError(f"key {key!r} given more than once, got {pair!r}")
            parsed[key] = value
        return parsed

    def _parse_one(self, pair: str) -> tuple[str, T]:
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"expected KEY=VALUE, got {pair!r}")
        return key, self._values.parse(raw)


class MetadataVisibility:
    """Classifies node metadata keys: descriptive stay visible, opaque ids are excluded."""

    def __init__(self, opaque_keys: frozenset[str] = OPAQUE_KEYS) -> None:
        self._opaque_keys: frozenset[str] = opaque_keys

    def excluded(self, metadata: Mapping[str, Any]) -> list[str]:
        """Keys to hide from both embedding and the LLM, sorted for stability."""
        return sorted(key for key in metadata if key in self._opaque_keys)
