"""Parse cache: a PDF is parsed once per extractor version, not once per run.

Parsing dominates ingestion — a mean of 101.9s per document and 351s for the
largest, against a few seconds for chunking and storing. So a change to the
chunker has to re-index, but must never re-parse.

The cached value is the ``ExtractedDoc`` itself, pickled. It cannot be JSON:
``PictureBlock`` carries a live PIL image that the figure-description stage
consumes, and encoding those as text would cost more than the cache saves.

The key is the file's bytes plus the extractor's name and version, so the same
PDF is shared across companies, a re-download of identical bytes hits, and an
extractor version bump misses cleanly. A cache is an optimisation, so an entry
that cannot be read is a miss rather than an error.
"""

import asyncio
import pickle
from pathlib import Path
from typing import Any, Final

from peerdex.parse import ExtractedDoc, Extractor
from peerdex.shared import cache
from peerdex.shared.logging import get_logger

log = get_logger("index")

_NS: Final[str] = "parse"


def _entry(pdf_path: Path, extractor: Extractor) -> str:
    """Where this document's parse lives, keyed by its bytes and the extractor."""
    key: str = cache.hash_key(pdf_path.read_bytes(), extractor.name, extractor.version)
    return f"{cache.join_path(_NS)}/{key}.pkl"


def _load(path: str) -> ExtractedDoc | None:
    """The cached parse, or None when it is absent or damaged."""
    fs: Any = cache.fs_and_root()[0]
    if not fs.exists(path):
        return None
    try:
        with fs.open(path, "rb") as handle:
            return pickle.load(handle)
    except Exception as exc:
        log.info(f"[parse] cache entry unreadable, re-parsing: {exc}")
        return None


def _store(path: str, doc: ExtractedDoc) -> None:
    """Keep the parse for the next run."""
    fs: Any = cache.fs_and_root()[0]
    fs.makedirs(cache.join_path(_NS), exist_ok=True)
    with fs.open(path, "wb") as handle:
        pickle.dump(doc, handle)


async def _extract(pdf_path: Path, extractor: Extractor) -> ExtractedDoc:
    """The extractor's async entry point when it has one, else the sync one."""
    if hasattr(extractor, "extract_async"):
        return await extractor.extract_async(pdf_path)
    return extractor.extract(pdf_path)


def _lookup(pdf_path: str | Path, extractor: Extractor) -> tuple[Path, str, ExtractedDoc | None]:
    """The resolved path, its cache location, and the cached parse if there is one."""
    resolved: Path = Path(pdf_path).resolve()
    entry: str = _entry(resolved, extractor)
    return resolved, entry, _load(entry)


async def parse_cached(pdf_path: str | Path, extractor: Extractor) -> ExtractedDoc:
    """The parse for this document, running the extractor only on a miss.

    Hashing a document and reading its cached parse are blocking reads of tens of
    megabytes, so they run off the event loop. Ingestion is async precisely so
    that several documents can be in flight at once, and a synchronous read here
    would stall every one of them.
    """
    resolved: Path
    entry: str
    cached: ExtractedDoc | None
    resolved, entry, cached = await asyncio.to_thread(_lookup, pdf_path, extractor)
    identity: str = f"{resolved.name} ({extractor.name} {extractor.version})"
    if cached is not None:
        log.info(f"[parse] cache hit {identity}")
        return cached

    log.info(f"[parse] cache miss {identity}")
    doc: ExtractedDoc = await _extract(resolved, extractor)
    await asyncio.to_thread(_store, entry, doc)
    return doc
