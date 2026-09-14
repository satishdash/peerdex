"""Filters rendered as the SQL LanceDB pushes down to the rows."""

import re
from collections.abc import Mapping
from typing import ClassVar

from shared.metadata import Scalar


class Predicates:
    """Renders filters as the SQL LanceDB pushes down to the rows."""

    _SAFE_KEY: ClassVar[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    @classmethod
    def attributes(cls, pairs: Mapping[str, tuple[Scalar, ...]]) -> str:
        """SQL predicate over stored metadata: AND across keys, OR within a key.

        Args:
            pairs: Each attribute key with the values admitted for it.

        Returns:
            The predicate, empty when no key was given.
        """
        return " AND ".join(cls._clause(key, values) for key, values in pairs.items())

    @staticmethod
    def document(doc_id: str) -> str:
        """LanceDB predicate matching every row of one indexed document.

        The document hash is matched under the key the chunker owns, because a
        framework writer reserves ``doc_id`` in stored metadata for its own use.

        Args:
            doc_id: The document's content-addressed id.

        Returns:
            The predicate.
        """
        return f"metadata.source_doc_id = '{doc_id}'"

    @classmethod
    def _clause(cls, key: str, values: tuple[Scalar, ...]) -> str:
        """One key's clause, equality for a single value and IN for several.

        Attribute keys can arrive from a sidecar file, so anything that is not a plain
        identifier is refused rather than interpolated into the query.

        Args:
            key: The metadata key to filter on.
            values: The values admitted for that key.

        Returns:
            The clause.

        Raises:
            ValueError: If the key is not a plain identifier.
        """
        if not cls._SAFE_KEY.match(key):
            raise ValueError(f"unsafe attribute key: {key!r}")
        rendered: str = ", ".join(cls._literal(v) for v in values)
        if len(values) == 1:
            return f"metadata.{key} = {rendered}"
        return f"metadata.{key} IN ({rendered})"

    @staticmethod
    def _literal(value: Scalar) -> str:
        """One filter value as a SQL literal, quoting and escaping strings.

        Args:
            value: The value to render.

        Returns:
            The literal.
        """
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"
