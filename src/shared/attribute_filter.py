"""A node-metadata predicate: AND across keys, OR within a key."""

from collections.abc import Mapping
from typing import Any

from shared.metadata import Metadata, Scalar, Scalars


class AttributeFilter:
    """Node-metadata predicate: AND across keys, OR within a key, company always on."""

    def __init__(self, company: str, attributes: Mapping[str, Scalars] | None = None) -> None:
        """Build the filter, with company always present.

        Args:
            company: The company every query is narrowed to.
            attributes: Further keys, each admitting one or more values.
        """
        self.pairs: dict[str, tuple[Scalar, ...]] = {
            "company": (company.strip().lower(),),
            **{key: self._admitted(key, values) for key, values in (attributes or {}).items()},
        }

    def matches(self, metadata: Mapping[str, Any]) -> bool:
        """Whether a node satisfies every key of this filter.

        Args:
            metadata: The node's stored metadata.

        Returns:
            Whether the node's value for every filter key is one of that key's values.
        """
        return all(metadata.get(key) in values for key, values in self.pairs.items())

    @staticmethod
    def _admitted(key: str, values: Scalars) -> tuple[Scalar, ...]:
        """The values admitted for one key, canonicalised and type-checked.

        Args:
            key: The attribute key.
            values: One value or several.

        Returns:
            The admitted values.

        Raises:
            ValueError: If the values are not all of one type.
        """
        canonical: tuple[Scalar, ...] = tuple(
            Metadata.canonical(value)
            for value in ((values,) if Metadata.is_scalar(values) else values)
        )
        if len({type(value) for value in canonical}) != 1:
            raise ValueError(
                f"filter {key!r} needs one or more values of a single type, got {canonical!r}"
            )
        return canonical
