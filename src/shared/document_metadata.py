"""Identity of one indexed document, plus its validated free-form attributes."""

from collections.abc import Mapping

from shared.metadata import Metadata, Scalar


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
        """Compose one document's metadata.

        Args:
            company: The company the document belongs to.
            year: The reporting year.
            source_uri: Where the document came from.
            extractor: The extractor that parsed it.
            attributes: Free-form scalar attributes from the caller.
        """
        self.company: str = company.strip().lower()
        self.year: int = int(year)
        self.source_uri: str = source_uri
        self.extractor: str = extractor.strip().lower()
        self.attributes: dict[str, Scalar] = {
            key: self._validated(key, value) for key, value in (attributes or {}).items()
        }

    @staticmethod
    def _validated(key: str, value: Scalar) -> Scalar:
        """One attribute, checked against the reserved keys and the scalar rule.

        Args:
            key: The attribute key.
            value: The attribute value.

        Returns:
            The canonical value.

        Raises:
            ValueError: If the key is reserved or the value is not a scalar.
        """
        if key in Metadata.RESERVED:
            raise ValueError(f"attribute {key!r} shadows a reserved metadata key")
        if not Metadata.is_scalar(value):
            raise ValueError(f"attribute {key!r} must be a scalar, got {type(value).__name__}")
        return Metadata.canonical(value)
