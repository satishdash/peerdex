"""JSON blobs on whatever filesystem the configured URI names."""

import json
from typing import Any

import fsspec


class BlobStore:
    """Reads and writes JSON blobs through fsspec, so local and cloud behave alike."""

    @staticmethod
    def join(base: str, *parts: str) -> str:
        """One URI from a base and the parts beneath it.

        Args:
            base: The base URI.
            parts: Path segments beneath it.

        Returns:
            The joined URI.
        """
        return base.rstrip("/") + "/" + "/".join(p.strip("/") for p in parts)

    @staticmethod
    def read(path: str) -> dict[str, Any] | None:
        """The JSON at this path, or None when it is absent.

        Args:
            path: The blob URI.

        Returns:
            The decoded blob, or None.
        """
        fs = fsspec.get_fs_token_paths(path)[0]
        if not fs.exists(path):
            return None
        with fs.open(path, "r") as handle:
            return json.loads(handle.read())

    @staticmethod
    def write(path: str, value: dict[str, Any]) -> None:
        """Write JSON to this path, creating the directory above it.

        Args:
            path: The blob URI.
            value: The payload to store.
        """
        fs = fsspec.get_fs_token_paths(path)[0]
        fs.makedirs(path.rsplit("/", 1)[0], exist_ok=True)
        with fs.open(path, "w") as handle:
            handle.write(json.dumps(value, ensure_ascii=False))
