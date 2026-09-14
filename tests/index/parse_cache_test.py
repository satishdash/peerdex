"""A parse is paid for once per document and extractor, not once per run."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

import fsspec
import pytest
from pytest_mock import MockerFixture

from index import ParseCache
from parse import ExtractedDoc, ParagraphBlock
from shared.settings import DoclingCfg, DoclingRsCfg, XbergCfg

_SETTINGS: Final[str] = "index.parse_cache.get_settings"


def _settings(hierarchy: bool = False, dpi: int = 300) -> Any:
    """A settings stub carrying only the sections the cache key fingerprints."""
    return SimpleNamespace(
        docling=DoclingCfg(artifacts_path=""),
        docling_rs=DoclingRsCfg(heading_hierarchy=hierarchy),
        xberg=XbergCfg(target_dpi=dpi),
    )


def _doc(text: str) -> ExtractedDoc:
    """Smallest well-formed ExtractedDoc, identifiable by its paragraph text."""
    return ExtractedDoc(
        blocks=[ParagraphBlock(kind="paragraph", text=text, page_no=1, heading_path=[])],
        pages=[],
        source_meta={"extractor_name": "fake", "extractor_version": "1"},
    )


class _Sync:
    """Extractor that counts how many times the real parse was performed."""

    def __init__(self, text: str = "parsed", version: str = "1") -> None:
        self.name: str = "fake"
        self.version: str = version
        self.calls: int = 0
        self._text: str = text

    def extract(self, pdf_path: str | Path) -> ExtractedDoc:
        self.calls += 1
        return _doc(self._text)

    async def extract_async(self, pdf_path: str | Path) -> ExtractedDoc:
        return self.extract(pdf_path)


class _Async(_Sync):
    """Extractor whose async entry point does the work, as the xberg one does."""

    def __init__(self) -> None:
        super().__init__()
        self.async_calls: int = 0

    async def extract_async(self, pdf_path: str | Path) -> ExtractedDoc:
        self.async_calls += 1
        return _doc("parsed async")


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    """A file on disk, since the cache key is derived from its bytes."""
    path: Path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF-1.7 pretend bytes")
    return path


@pytest.fixture
def two_pdfs(tmp_path: Path) -> tuple[Path, Path]:
    """Two documents with different bytes, so they must not share a cache entry."""
    first: Path = tmp_path / "a.pdf"
    second: Path = tmp_path / "b.pdf"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    return first, second


@pytest.fixture
def cache(mocker: MockerFixture) -> Any:
    """An in-memory cache root, so no test touches the real cache directory."""
    fs: Any = fsspec.filesystem("memory")
    fs.store.clear()
    fs.pseudo_dirs.clear()
    mocker.patch("shared.cache.Cache.fs_and_root", return_value=(fs, "/cache"))
    return fs


async def test_given_no_cached_parse_when_parsing_then_the_extractor_runs_once(
    pdf: Path, cache: Any
) -> None:
    """A cold cache must still produce the parse, and exactly one parse."""
    extractor: _Sync = _Sync()

    result: ExtractedDoc = await ParseCache.get(pdf, extractor)

    assert extractor.calls == 1
    assert result.blocks[0].text == "parsed"


async def test_given_a_cached_parse_when_parsing_again_then_the_extractor_is_not_called_again(
    pdf: Path, cache: Any
) -> None:
    """This is the whole point: changing the chunker must never re-parse the PDF."""
    extractor: _Sync = _Sync()

    first: ExtractedDoc = await ParseCache.get(pdf, extractor)
    second: ExtractedDoc = await ParseCache.get(pdf, extractor)

    assert extractor.calls == 1
    assert first.blocks[0].text == second.blocks[0].text == "parsed"


async def test_given_a_new_extractor_version_when_parsing_then_the_cache_is_missed(
    pdf: Path, cache: Any
) -> None:
    """A version bump means behaviour changed, so the old parse must not be reused."""
    await ParseCache.get(pdf, _Sync(text="old", version="1"))
    bumped: _Sync = _Sync(text="new", version="2")

    result: ExtractedDoc = await ParseCache.get(pdf, bumped)

    assert bumped.calls == 1
    assert result.blocks[0].text == "new"


async def test_given_different_documents_when_parsing_then_each_is_parsed_once(
    two_pdfs: tuple[Path, Path], cache: Any
) -> None:
    """The key is the file's bytes, so two documents must not share one entry."""
    extractor: _Sync = _Sync()

    await ParseCache.get(two_pdfs[0], extractor)
    await ParseCache.get(two_pdfs[1], extractor)

    assert extractor.calls == 2


async def test_given_an_unreadable_entry_when_parsing_then_it_falls_back_to_the_extractor(
    pdf: Path, cache: Any
) -> None:
    """A cache is an optimisation; a damaged entry must never fail the ingest."""
    extractor: _Sync = _Sync()
    await ParseCache.get(pdf, extractor)
    entries: list[str] = cache.find("/cache")
    assert len(entries) == 1
    with cache.open(entries[0], "wb") as handle:
        handle.write(b"not a pickle")

    result: ExtractedDoc = await ParseCache.get(pdf, extractor)

    assert extractor.calls == 2
    assert result.blocks[0].text == "parsed"


async def test_given_an_async_extractor_when_parsing_then_the_async_entry_point_is_used(
    pdf: Path, cache: Any
) -> None:
    """The cache takes the async entry point, never the sync one behind it."""
    extractor: _Async = _Async()

    result: ExtractedDoc = await ParseCache.get(pdf, extractor)

    assert extractor.async_calls == 1
    assert extractor.calls == 0
    assert result.blocks[0].text == "parsed async"


async def test_given_a_changed_parse_setting_when_parsing_then_the_cache_is_missed(
    pdf: Path, cache: Any, mocker: MockerFixture
) -> None:
    """A knob that changes parse output must not serve a parse made under the old one."""
    mocker.patch(_SETTINGS, return_value=_settings(hierarchy=False))
    await ParseCache.get(pdf, _Sync(text="flat"))
    mocker.patch(_SETTINGS, return_value=_settings(hierarchy=True))
    nested: _Sync = _Sync(text="nested")

    result: ExtractedDoc = await ParseCache.get(pdf, nested)

    assert nested.calls == 1
    assert result.blocks[0].text == "nested"


async def test_given_unchanged_parse_settings_when_parsing_then_the_cache_still_hits(
    pdf: Path, cache: Any, mocker: MockerFixture
) -> None:
    """The fingerprint has to be stable, or the cache would never hit at all."""
    mocker.patch(_SETTINGS, return_value=_settings())
    extractor: _Sync = _Sync()

    await ParseCache.get(pdf, extractor)
    mocker.patch(_SETTINGS, return_value=_settings())
    await ParseCache.get(pdf, extractor)

    assert extractor.calls == 1
