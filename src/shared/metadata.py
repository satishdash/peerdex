"""The metadata vocabulary: which keys the system owns, and what a scalar is."""

from collections.abc import Sequence
from typing import ClassVar, TypeIs

type Scalar = str | int | float | bool
type Scalars = Scalar | Sequence[Scalar]


class Metadata:
    """The keys the system reserves, and the scalar rules every attribute obeys."""

    RESERVED: ClassVar[frozenset[str]] = frozenset(
        {
            "doc_id",
            "source_doc_id",
            "parent_id",
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
    OPAQUE: ClassVar[frozenset[str]] = frozenset(
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

    @staticmethod
    def is_scalar(value: object) -> TypeIs[Scalar]:
        """Whether a value is one the store can hold as a column.

        Args:
            value: The value to test.

        Returns:
            Whether it is a scalar.
        """
        return isinstance(value, str | int | float | bool)

    @staticmethod
    def canonical(value: Scalar) -> Scalar:
        """Booleans become 1/0: LanceDB dense filters cannot express a boolean literal.

        Args:
            value: The value to normalise.

        Returns:
            The canonical value.
        """
        return int(value) if isinstance(value, bool) else value
