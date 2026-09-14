"""Permanent failures, kept for audit and re-run.

Entries are never read back by the pipeline. They exist so a crash in third-party
code survives the terminal scrollback of a long run.
"""

from typing import Any, ClassVar

from shared.logging import Logging
from shared.settings import get_settings
from vlm.blob_store import BlobStore


class DeadLetterQueue:
    """Keeps a permanent-failure record per document, under ``dlq/<doc_id>/<key>.json``."""

    _LOG: ClassVar[Any] = Logging.get("vlm.dlq")
    _DIR: ClassVar[str] = "dlq"

    @classmethod
    def put(cls, doc_id: str, key: str, payload: dict[str, Any]) -> None:
        """Record one permanent failure. Best-effort: failing to record is never fatal.

        Args:
            doc_id: The document the failure belongs to.
            key: What failed, as a stable key.
            payload: What is worth keeping about the failure.
        """
        path: str = BlobStore.join(
            get_settings().storage.cache_uri, cls._DIR, doc_id, f"{key}.json"
        )
        try:
            BlobStore.write(path, payload)
            cls._LOG.warning(f"[dlq] doc={doc_id} key={key[:12]} -> {path}")
        except Exception as e:
            cls._LOG.error(f"[dlq] failed to write {key[:12]}: {e}")
