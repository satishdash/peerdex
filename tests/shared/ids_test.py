"""Unit tests for extractor-scoped document identity."""

from pathlib import Path

from peerdex.shared.ids import doc_id, node_id


def test_given_same_file_when_extractor_differs_then_doc_ids_differ(tmp_path: Path) -> None:
    pdf: Path = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF same bytes")
    docling_id: str = doc_id("acme", pdf, "docling")
    liteparse_id: str = doc_id("acme", pdf, "liteparse")
    assert docling_id != liteparse_id
    assert len(docling_id) == 16
    assert len(liteparse_id) == 16


def test_given_same_inputs_when_hashed_twice_then_doc_id_stable(tmp_path: Path) -> None:
    pdf: Path = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF same bytes")
    assert doc_id(" Acme ", pdf, " Docling ") == doc_id("acme", pdf, "docling")


def test_given_same_index_when_kinds_differ_then_node_ids_differ() -> None:
    """A parent counter and a child counter both start at 0."""
    assert node_id("abc", 0, "p") != node_id("abc", 0, "c")


def test_given_kind_and_index_when_built_then_node_id_is_doc_kind_index() -> None:
    """The shape is relied on when reading a dumped chunk back."""
    assert node_id("abc", 7, "p") == "abc:p7"
    assert node_id("abc", 7, "c") == "abc:c7"
