"""Per-image cache of vision-model descriptions.

Key = sha256(image bytes + model + prompt version), so re-running ingest skips the
API entirely on a hit. A cache is an optimisation, so a read that fails is a miss
rather than an error.
"""

import hashlib
from typing import Any, ClassVar

from shared.logging import Logging
from shared.settings import get_settings
from vlm.blob_store import BlobStore


class DescriptionCache:
    """One description per image, keyed by the image, the model and the prompt version."""

    _LOG: ClassVar[Any] = Logging.get("vlm.description_cache")

    @staticmethod
    def key(image_bytes: bytes, *, vlm_model: str, prompt_version: int) -> str:
        """The cache key for one image under one model and prompt version.

        Args:
            image_bytes: The rendered figure.
            vlm_model: The vision model that would describe it.
            prompt_version: The prompt version in force.

        Returns:
            The key.
        """
        h = hashlib.sha256()
        h.update(image_bytes)
        h.update(b"\0")
        h.update(vlm_model.encode())
        h.update(b"\0")
        h.update(str(prompt_version).encode())
        return h.hexdigest()

    @classmethod
    def get(cls, key: str) -> dict[str, Any] | None:
        """The cached description, or None when it is absent or unreadable.

        Args:
            key: The cache key.

        Returns:
            The description, or None.
        """
        try:
            return BlobStore.read(cls._path(key))
        except Exception as e:
            cls._LOG.debug(f"[cache] read miss {key[:12]}: {e}")
            return None

    @classmethod
    def put(cls, key: str, value: dict[str, Any]) -> None:
        """Keep a description. Best-effort: a failed write is never fatal.

        Args:
            key: The cache key.
            value: The description to store.
        """
        try:
            BlobStore.write(cls._path(key), value)
        except Exception as e:
            cls._LOG.warning(f"[cache] write failed {key[:12]}: {e}")

    @staticmethod
    def _path(key: str) -> str:
        """Where this key's description lives.

        Args:
            key: The cache key.

        Returns:
            The blob URI.
        """
        return BlobStore.join(get_settings().vlm.cache_dir, f"{key}.json")
