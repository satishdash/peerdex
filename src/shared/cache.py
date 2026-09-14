"""On-disk cache, addressed by namespace and key through fsspec.

fsspec is what lets the same code write to a local directory in development and to
object storage in production, with no branch at the call site.
"""

import hashlib
import json
from functools import lru_cache
from typing import Any

import fsspec

from shared.settings import get_settings


class Cache:
    """Namespaced JSON blobs under the configured cache root."""

    _CHUNKS: str = "chunks"

    @staticmethod
    @lru_cache(maxsize=1)
    def fs_and_root() -> tuple[Any, str]:
        """The filesystem behind the cache URI, and the root path inside it.

        Returns:
            The filesystem and its root path.
        """
        uri = get_settings().storage.cache_uri
        fs, _, paths = fsspec.get_fs_token_paths(uri)
        return fs, paths[0]

    @classmethod
    def join_path(cls, *parts: str) -> str:
        """One path under the cache root.

        Args:
            parts: Path segments beneath the root.

        Returns:
            The joined path.
        """
        _, root = cls.fs_and_root()
        return root.rstrip("/") + "/" + "/".join(p.strip("/") for p in parts)

    @classmethod
    def chunk_debug_dir(cls) -> str:
        """Directory holding the per-document chunk dumps.

        Returns:
            The directory path.
        """
        return cls.join_path(cls._CHUNKS)

    @classmethod
    def chunk_debug_path(cls, doc_id: str) -> str:
        """Where one document's chunk dump lives.

        Args:
            doc_id: The document.

        Returns:
            The file path.
        """
        return f"{cls.chunk_debug_dir()}/{doc_id}.md"

    @staticmethod
    def hash_key(*parts: str | bytes) -> str:
        """One cache key from every part that should change it.

        Args:
            parts: The parts to hash, text or bytes.

        Returns:
            The hex digest.
        """
        h = hashlib.sha256()
        for p in parts:
            h.update(p.encode() if isinstance(p, str) else p)
        return h.hexdigest()

    @classmethod
    def get_json(cls, namespace: str, key: str) -> dict | None:
        """The cached blob, or None when it is absent.

        Args:
            namespace: The namespace holding the key.
            key: The cache key.

        Returns:
            The decoded blob, or None.
        """
        fs, _ = cls.fs_and_root()
        path: str = cls.join_path(namespace, f"{key}.json")
        if not fs.exists(path):
            return None
        with fs.open(path, "r") as handle:
            return json.load(handle)

    @classmethod
    def put_json(cls, namespace: str, key: str, value: dict) -> None:
        """Keep a blob under this namespace and key.

        Args:
            namespace: The namespace to store under.
            key: The cache key.
            value: The payload.
        """
        fs, _ = cls.fs_and_root()
        fs.makedirs(cls.join_path(namespace), exist_ok=True)
        with fs.open(cls.join_path(namespace, f"{key}.json"), "w") as handle:
            json.dump(value, handle)

    @classmethod
    def exists(cls, namespace: str, key: str) -> bool:
        """Whether this namespace already holds this key.

        Args:
            namespace: The namespace to look in.
            key: The cache key.

        Returns:
            Whether the blob is present.
        """
        fs, _ = cls.fs_and_root()
        return bool(fs.exists(cls.join_path(namespace, f"{key}.json")))
