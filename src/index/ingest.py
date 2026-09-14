"""Ingestion: a PDF, or a directory of them, all the way to searchable rows.

doc_id is content-addressed, so re-indexing a file first deletes its prior LanceDB
rows and replaces them cleanly.
"""

import asyncio
import traceback
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

import lancedb
from chunk import HierarchicalChunker
from index.child_store import ChildStore
from index.embeddings import Embeddings
from index.parent_store import ParentStore
from index.parse_cache import ParseCache
from index.predicates import Predicates
from index.table_indexes import TableIndexes
from index.tables import Tables
from parse import ExtractedDoc, Extractor, ExtractorRegistry
from shared.document_metadata import DocumentMetadata
from shared.ids import Ids
from shared.logging import Logging
from shared.metadata import Scalar
from shared.settings import get_settings, resolve_domain
from vlm import DeadLetterQueue


class Ingest:
    """Takes a PDF, or a directory of them, all the way to searchable rows."""

    _LOG: ClassVar[Any] = Logging.get("index")
    _PARSE_FAILURE: ClassVar[str] = "parse"

    @classmethod
    async def document(
        cls,
        pdf_path: str | Path,
        *,
        company: str,
        domain: str,
        year: int,
        extractor: str | None = None,
        attributes: Mapping[str, Scalar] | None = None,
    ) -> dict[str, Any]:
        """Extract, chunk, embed, store and index one document.

        Returns with the document's rows inside both indexes. Indexing is not a separate
        call, because one that can be forgotten will be.

        Args:
            pdf_path: The document to ingest.
            company: The company the document belongs to.
            domain: The domain owning the table.
            year: The reporting year.
            extractor: Which extractor to use, or None for the default.
            attributes: Free-form scalar attributes attached to every node.

        Returns:
            What was stored, or a failure record when the document could not be read.
        """
        resolved: str = resolve_domain(domain)
        result: dict[str, Any] = await cls._or_record(
            pdf_path,
            company=company,
            domain=resolved,
            year=year,
            extractor=extractor,
            attributes=attributes,
        )
        if cls._stored_any([result]):
            await asyncio.to_thread(TableIndexes.build, resolved)
        return result

    @classmethod
    async def directory(
        cls,
        dir_path: str | Path,
        *,
        company: str,
        domain: str,
        year: int,
        extractor: str | None = None,
        attributes: Mapping[str, Scalar] | None = None,
    ) -> list[dict[str, Any]]:
        """Index every PDF in a directory, all under the one year given.

        Returns with every document searchable. Sorted so a run is reproducible and a
        partial one is resumable by eye. Sequential for now: document-level concurrency
        is its own piece of work, with its own measurement, because the largest document
        dominates the wall clock.

        The indexes are brought up to date once at the end rather than per document,
        because doing so compacts the whole table.

        Args:
            dir_path: The directory holding the PDFs.
            company: The company the documents belong to.
            domain: The domain owning the table.
            year: The reporting year.
            extractor: Which extractor to use, or None for the default.
            attributes: Free-form scalar attributes attached to every node.

        Returns:
            One record per document, in sorted order.

        Raises:
            ValueError: If the directory holds no PDF.
        """
        resolved: str = resolve_domain(domain)
        directory: Path
        pdfs: list[Path]
        directory, pdfs = await asyncio.to_thread(cls._pdfs_in, dir_path)
        if not pdfs:
            raise ValueError(f"no PDFs in {directory}")

        cls._LOG.info(f"[index] ingesting {len(pdfs)} documents from {directory}")
        results: list[dict[str, Any]] = await cls._each(
            pdfs,
            company=company,
            domain=resolved,
            year=year,
            extractor=extractor,
            attributes=attributes,
        )
        if cls._stored_any(results):
            await asyncio.to_thread(TableIndexes.build, resolved)
        return results

    @classmethod
    async def _each(
        cls,
        pdfs: list[Path],
        *,
        company: str,
        domain: str,
        year: int,
        extractor: str | None,
        attributes: Mapping[str, Scalar] | None,
    ) -> list[dict[str, Any]]:
        """Ingest each document in turn, keeping a record for every one.

        Args:
            pdfs: The documents to ingest, in order.
            company: The company the documents belong to.
            domain: The resolved domain.
            year: The reporting year.
            extractor: Which extractor to use, or None for the default.
            attributes: Free-form scalar attributes attached to every node.

        Returns:
            One record per document.
        """
        results: list[dict[str, Any]] = []
        for pdf in pdfs:
            results.append(
                await cls._or_record(
                    pdf,
                    company=company,
                    domain=domain,
                    year=year,
                    extractor=extractor,
                    attributes=attributes,
                )
            )
        return results

    @classmethod
    async def _or_record(
        cls,
        pdf_path: str | Path,
        *,
        company: str,
        domain: str,
        year: int,
        extractor: str | None,
        attributes: Mapping[str, Scalar] | None,
    ) -> dict[str, Any]:
        """One document ingested, or a failure record when its extractor cannot read it.

        A corpus is a set of documents, and one of them being unreadable must not cost
        the others. Any exception counts: an extractor is third-party code and the ways
        it can fail are not ours to enumerate.

        Args:
            pdf_path: The document to ingest.
            company: The company the document belongs to.
            domain: The resolved domain.
            year: The reporting year.
            extractor: Which extractor to use, or None for the default.
            attributes: Free-form scalar attributes attached to every node.

        Returns:
            What was stored, or the failure record.
        """
        try:
            return await cls._one(
                pdf_path,
                company=company,
                domain=domain,
                year=year,
                extractor=extractor,
                attributes=attributes,
            )
        except Exception as exc:
            return cls._failure(pdf_path, company, extractor, exc)

    @classmethod
    async def _one(
        cls,
        pdf_path: str | Path,
        *,
        company: str,
        domain: str,
        year: int,
        extractor: str | None,
        attributes: Mapping[str, Scalar] | None,
    ) -> dict[str, Any]:
        """Extract, chunk, embed and store one document, leaving the indexes to the caller.

        Private because an ingest that stops here leaves rows outside the indexes. The
        two public entry points both finish the job; a directory does it once at the end
        rather than per document, because optimising compacts the whole table.

        Args:
            pdf_path: The document to ingest.
            company: The company the document belongs to.
            domain: The resolved domain.
            year: The reporting year.
            extractor: Which extractor to use, or None for the default.
            attributes: Free-form scalar attributes attached to every node.

        Returns:
            What was stored, counted by kind.
        """
        pdf_abs: str = str(await asyncio.to_thread(Path(pdf_path).resolve))

        extractor_inst: Extractor = ExtractorRegistry.create(extractor)
        ed: ExtractedDoc = await ParseCache.get(pdf_abs, extractor_inst)

        extractor_name: str = str(ed.source_meta["extractor_name"])
        doc_meta: DocumentMetadata = cls._metadata(
            Path(pdf_abs), company, year, extractor_name, attributes
        )
        did: str = Ids.document(company, pdf_abs, extractor_name)

        cls._LOG.info(
            f"[index] doc_id={did} domain={domain} company={doc_meta.company} "
            f"extractor={doc_meta.extractor} attributes={doc_meta.attributes} source={pdf_abs}"
        )

        parent_nodes, child_nodes = await HierarchicalChunker().chunk(
            ed,
            doc_id=did,
            metadata=doc_meta,
        )

        cls._clear(did, domain)
        await ChildStore(domain).put(did, child_nodes, Embeddings.model())
        parents: int = ParentStore(domain).put(did, parent_nodes)

        cls._LOG.info(f"[index] persisted {len(child_nodes)} nodes, {parents} parents ({did})")
        return {
            "doc_id": did,
            "nodes": len(child_nodes),
            "tables": sum(1 for n in child_nodes if n.metadata.get("is_table")),
            "figures": sum(1 for n in child_nodes if n.metadata.get("is_figure")),
            "extractor": ed.source_meta.get("extractor_name"),
            "attributes": doc_meta.attributes,
        }

    @classmethod
    def _clear(cls, doc_id: str, domain: str) -> None:
        """Remove any prior rows for this doc_id so a re-index is clean.

        Args:
            doc_id: The document whose rows to clear.
            domain: The domain owning the table.
        """
        s = get_settings()
        try:
            db = lancedb.connect(s.storage.lancedb_uri)
            if Tables.exists(db, domain):
                tbl = db.open_table(domain)
                tbl.delete(Predicates.document(doc_id))
                cls._LOG.info(f"[index] cleared prior rows for doc_id={doc_id}")
        except Exception as e:
            cls._LOG.debug(f"[index] delete prior rows skipped: {e}")

    @classmethod
    def _failure(
        cls, pdf_path: str | Path, company: str, extractor: str | None, exc: Exception
    ) -> dict[str, Any]:
        """Keep an unreadable document's traceback, and describe the skip to the caller.

        The traceback goes to the dead-letter queue rather than only to the terminal,
        because an upstream crash is reported as a bug and cannot be recovered from
        scrollback once a sixteen-document run has scrolled past it.

        Args:
            pdf_path: The document that could not be read.
            company: The company it belongs to.
            extractor: Which extractor was asked for, or None for the default.
            exc: The failure.

        Returns:
            The failure record.
        """
        resolved: str = str(Path(pdf_path).resolve())
        instance: Extractor = ExtractorRegistry.create(extractor)
        did: str = Ids.document(company, resolved, instance.name)
        detail: str = f"{type(exc).__name__}: {exc}"
        DeadLetterQueue.put(
            did,
            cls._PARSE_FAILURE,
            {
                "source": resolved,
                "extractor": instance.name,
                "extractor_version": instance.version,
                "error": detail,
                "traceback": "".join(traceback.format_exception(exc)),
            },
        )
        cls._LOG.error(f"[index] skipped {resolved}: {detail}")
        return {"doc_id": did, "source": resolved, "failed": True, "error": detail}

    @staticmethod
    def _metadata(
        pdf_abs: Path,
        company: str,
        year: int,
        extractor_name: str,
        attributes: Mapping[str, Scalar] | None,
    ) -> DocumentMetadata:
        """Compose the document metadata. Attributes come from the caller, nowhere else.

        Args:
            pdf_abs: The resolved document path.
            company: The company the document belongs to.
            year: The reporting year.
            extractor_name: The extractor that produced the parse.
            attributes: Free-form scalar attributes attached to every node.

        Returns:
            The document metadata.
        """
        return DocumentMetadata(
            company=company,
            year=int(year),
            source_uri=str(pdf_abs),
            extractor=extractor_name,
            attributes=dict(attributes or {}),
        )

    @staticmethod
    def _pdfs_in(dir_path: str | Path) -> tuple[Path, list[Path]]:
        """The resolved directory and the PDFs directly inside it, sorted.

        Args:
            dir_path: The directory to scan.

        Returns:
            The resolved directory and its PDFs.
        """
        directory: Path = Path(dir_path).expanduser().resolve()
        return directory, sorted(p for p in directory.glob("*.pdf") if p.is_file())

    @staticmethod
    def _stored_any(results: list[dict[str, Any]]) -> bool:
        """Whether any document reached the table, since indexing an absent one would fail.

        Args:
            results: The records returned for this run.

        Returns:
            Whether at least one document stored rows.
        """
        return any(not result.get("failed") for result in results)
