"""Which metadata keys stay visible to the embedder and the model, and which do not."""

from collections.abc import Mapping
from typing import Any

from shared.metadata import Metadata


class MetadataVisibility:
    """Classifies node metadata keys: descriptive stay visible, opaque ids are excluded."""

    def __init__(self, opaque_keys: frozenset[str] = Metadata.OPAQUE) -> None:
        """Bind to the set of keys treated as opaque.

        Args:
            opaque_keys: The keys to hide.
        """
        self._opaque_keys: frozenset[str] = opaque_keys

    def excluded(self, metadata: Mapping[str, Any]) -> list[str]:
        """Keys to hide from both embedding and the model.

        Args:
            metadata: The node's metadata.

        Returns:
            The excluded keys, sorted for stability.
        """
        return sorted(key for key in metadata if key in self._opaque_keys)
