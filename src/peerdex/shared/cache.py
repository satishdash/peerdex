"""Abstract cache with pluggable backends.

Public API (unchanged from before):
    get_json(ns, key)  → dict | None
    put_json(ns, key, value)
    exists(ns, key)    → bool
    hash_key(*parts)   → str
    join_path(*parts)  → str       # fsspec-only helper, kept for VLM cache
    fs_and_root()                  # fsspec-only helper, kept for VLM cache

To swap backends in prod (e.g. Dragonfly/Redis), implement ``CacheBackend``
and register it via ``set_backend()``. Default is ``FsspecBackend``.
"""

import hashlib
import json
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Any

import fsspec

from peerdex.shared.settings import get_settings


# ---------- protocol ----------

class CacheBackend(ABC):
    @abstractmethod
    def get(self, namespace: str, key: str) -> dict | None: ...

    @abstractmethod
    def put(self, namespace: str, key: str, value: dict) -> None: ...

    @abstractmethod
    def exists(self, namespace: str, key: str) -> bool: ...


# ---------- fsspec backend (default) ----------

class FsspecBackend(CacheBackend):
    def _fs(self) -> tuple[Any, str]:
        return fs_and_root()

    def get(self, namespace: str, key: str) -> dict | None:
        fs, _ = self._fs()
        path = join_path(namespace, f"{key}.json")
        if not fs.exists(path):
            return None
        with fs.open(path, "r") as f:
            return json.load(f)

    def put(self, namespace: str, key: str, value: dict) -> None:
        fs, _ = self._fs()
        path = join_path(namespace, f"{key}.json")
        fs.makedirs(join_path(namespace), exist_ok=True)
        with fs.open(path, "w") as f:
            json.dump(value, f)

    def exists(self, namespace: str, key: str) -> bool:
        fs, _ = self._fs()
        return bool(fs.exists(join_path(namespace, f"{key}.json")))


# ---------- backend registry ----------

_backend: CacheBackend | None = None


def set_backend(backend: CacheBackend) -> None:
    """Override the default fsspec backend (e.g. with a Redis/Dragonfly impl)."""
    global _backend
    _backend = backend


def _get_backend() -> CacheBackend:
    global _backend
    if _backend is None:
        _backend = FsspecBackend()
    return _backend


# ---------- fsspec helpers (kept for VLM cache / join_path users) ----------

@lru_cache(maxsize=1)
def fs_and_root() -> tuple[Any, str]:
    uri = get_settings().storage.cache_uri
    fs, _, paths = fsspec.get_fs_token_paths(uri)
    return fs, paths[0]


def join_path(*parts: str) -> str:
    _, root = fs_and_root()
    return root.rstrip("/") + "/" + "/".join(p.strip("/") for p in parts)


# ---------- public API (delegates to active backend) ----------

def hash_key(*parts: str | bytes) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode() if isinstance(p, str) else p)
    return h.hexdigest()


def get_json(namespace: str, key: str) -> dict | None:
    return _get_backend().get(namespace, key)


def put_json(namespace: str, key: str, value: dict) -> None:
    _get_backend().put(namespace, key, value)


def exists(namespace: str, key: str) -> bool:
    return _get_backend().exists(namespace, key)
