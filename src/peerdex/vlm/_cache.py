"""Per-image VLM cache (fsspec, GCS-ready).

Key = sha256(image_bytes + vlm_model + prompt_version) → JSON of the
parsed VLM response. Per-doc DLQ is a sibling fsspec dir; entries
written there are NEVER read back, only kept for audit / re-run.
"""

import hashlib
import json
from typing import Any

import fsspec

from peerdex.shared.logging import get_logger
from peerdex.shared.settings import get_settings

log = get_logger("vlm.cache")


def cache_key(image_bytes: bytes, *, vlm_model: str, prompt_version: int) -> str:
    h = hashlib.sha256()
    h.update(image_bytes)
    h.update(b"\0")
    h.update(vlm_model.encode())
    h.update(b"\0")
    h.update(str(prompt_version).encode())
    return h.hexdigest()


def _fs(uri: str):
    return fsspec.get_fs_token_paths(uri)[0]


def _join_uri(base: str, *parts: str) -> str:
    base = base.rstrip("/")
    return base + "/" + "/".join(p.strip("/") for p in parts)


def get(key: str) -> dict[str, Any] | None:
    """Return cached parsed VLM response, or None if absent."""
    s = get_settings()
    path = _join_uri(s.vlm.cache_dir, f"{key}.json")
    fs = _fs(path)
    try:
        if not fs.exists(path):
            return None
        with fs.open(path, "r") as f:
            return json.loads(f.read())
    except Exception as e:
        log.debug(f"[cache] read miss {key[:12]}: {e}")
        return None


def put(key: str, value: dict[str, Any]) -> None:
    """Best-effort write; cache misses are never fatal."""
    s = get_settings()
    path = _join_uri(s.vlm.cache_dir, f"{key}.json")
    fs = _fs(path)
    try:
        fs.makedirs(path.rsplit("/", 1)[0], exist_ok=True)
        with fs.open(path, "w") as f:
            f.write(json.dumps(value, ensure_ascii=False))
    except Exception as e:
        log.warning(f"[cache] write failed {key[:12]}: {e}")


def dlq_put(doc_id: str, key: str, payload: dict[str, Any]) -> None:
    """Write a permanent-failure record under cache/dlq/<doc_id>/<key>.json."""
    s = get_settings()
    path = _join_uri(s.storage.cache_uri, "dlq", doc_id, f"{key}.json")
    fs = _fs(path)
    try:
        fs.makedirs(path.rsplit("/", 1)[0], exist_ok=True)
        with fs.open(path, "w") as f:
            f.write(json.dumps(payload, ensure_ascii=False))
        log.warning(f"[dlq] doc={doc_id} key={key[:12]} → {path}")
    except Exception as e:  # pragma: no cover
        log.error(f"[dlq] failed to write {key[:12]}: {e}")
