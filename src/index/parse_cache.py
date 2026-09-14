"""Parse cache: a PDF is parsed once per extractor version, not once per run.

Parsing dominates ingestion — a mean of 101.9s per document and 351s for the
largest, against a few seconds for chunking and storing. So a change to the
chunker has to re-index, but must never re-parse.

The cached value is the ``ExtractedDoc`` itself, pickled. It cannot be JSON:
``PictureBlock`` carries a live PIL image that the figure-description stage
consumes, and encoding those as text would cost more than the cache saves.

The key is the file's bytes, the extractor's name and version, and a fingerprint
of the parse configuration, so the same PDF is shared across companies, a
re-download of identical bytes hits, and a version bump or a changed knob misses
cleanly. A cache is an optimisation, so an entry that cannot be read is a miss
rather than an error.
"""

import asyncio
import json
import pickle
from pathlib import Path
from typing import Any, ClassVar

from parse import ExtractedDoc, Extractor
from shared.cache import Cache
from shared.logging import Logging
from shared.settings import get_settings


class ParseCache:
    """Serves a document's parse from disk, running the extractor only on a miss."""

    _LOG: ClassVar[Any] = Logging.get("index")
    _NS: ClassVar[str] = "parse"
    _CFG_SECTIONS: ClassVar[tuple[str, ...]] = ("docling", "docling_rs", "xberg")

    @classmethod
    async def get(cls, pdf_path: str | Path, extractor: Extractor) -> ExtractedDoc:
        """The parse for this document, running the extractor only on a miss.

        Hashing a document and reading its cached parse are blocking reads of tens of
        megabytes, so they run off the event loop. Ingestion is async precisely so
        that several documents can be in flight at once, and a synchronous read here
        would stall every one of them.

        Args:
            pdf_path: The document to parse.
            extractor: The extractor to run on a miss.

        Returns:
            The parsed document, cached or freshly extracted.
        """
        resolved: Path
        entry: str
        cached: ExtractedDoc | None
        resolved, entry, cached = await asyncio.to_thread(cls._lookup, pdf_path, extractor)
        identity: str = f"{resolved.name} ({extractor.name} {extractor.version})"
        if cached is not None:
            cls._LOG.info(f"[parse] cache hit {identity}")
            return cached

        cls._LOG.info(f"[parse] cache miss {identity}")
        doc: ExtractedDoc = await extractor.extract_async(resolved)
        await asyncio.to_thread(cls._store, entry, doc)
        return doc

    @classmethod
    def _lookup(
        cls, pdf_path: str | Path, extractor: Extractor
    ) -> tuple[Path, str, ExtractedDoc | None]:
        """The resolved path, its cache location, and the cached parse if there is one.

        Args:
            pdf_path: The document being looked up.
            extractor: The extractor whose output would be cached.

        Returns:
            The resolved path, the cache entry path, and the cached parse or None.
        """
        resolved: Path = Path(pdf_path).resolve()
        entry: str = cls._entry(resolved, extractor)
        return resolved, entry, cls._load(entry)

    @classmethod
    def _entry(cls, pdf_path: Path, extractor: Extractor) -> str:
        """Where this parse lives, keyed by the document, the extractor and its config.

        Args:
            pdf_path: The resolved document path.
            extractor: The extractor whose output would be cached.

        Returns:
            The cache entry path.
        """
        key: str = Cache.hash_key(
            pdf_path.read_bytes(), extractor.name, extractor.version, cls._fingerprint()
        )
        return f"{Cache.join_path(cls._NS)}/{key}.pkl"

    @classmethod
    def _fingerprint(cls) -> str:
        """The parse-affecting configuration, condensed to one key component.

        An extractor's output depends on its settings as much as on its version, and
        the settings are nowhere in the version string. Folding them into the key
        means a changed knob misses cleanly instead of serving a parse produced under
        the old one. All parse sections are hashed together rather than only the
        running extractor's, so a new extractor needs no change here; the price is a
        re-parse that was not strictly required, never a stale answer.

        Returns:
            One hash covering every parse section of the configuration.
        """
        settings: Any = get_settings()
        blob: dict[str, Any] = {
            section: getattr(settings, section).model_dump() for section in cls._CFG_SECTIONS
        }
        return Cache.hash_key(json.dumps(blob, sort_keys=True))

    @classmethod
    def _load(cls, path: str) -> ExtractedDoc | None:
        """The cached parse, or None when it is absent or damaged.

        Args:
            path: The cache entry path.

        Returns:
            The cached parse, or None on a miss or an unreadable entry.
        """
        fs: Any = Cache.fs_and_root()[0]
        if not fs.exists(path):
            return None
        try:
            with fs.open(path, "rb") as handle:
                return pickle.load(handle)
        except Exception as exc:
            cls._LOG.info(f"[parse] cache entry unreadable, re-parsing: {exc}")
            return None

    @classmethod
    def _store(cls, path: str, doc: ExtractedDoc) -> None:
        """Keep the parse for the next run.

        Args:
            path: The cache entry path.
            doc: The parsed document to keep.
        """
        fs: Any = Cache.fs_and_root()[0]
        fs.makedirs(Cache.join_path(cls._NS), exist_ok=True)
        with fs.open(path, "wb") as handle:
            pickle.dump(doc, handle)
