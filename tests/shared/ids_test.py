"""Unit tests for extractor-scoped document identity."""

from pathlib import Path

from shared.ids import Ids


def test_given_same_file_when_extractor_differs_then_doc_ids_differ(tmp_path: Path) -> None:
    pdf: Path = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF same bytes")
    docling_id: str = Ids.document("acme", pdf, "docling")
    liteparse_id: str = Ids.document("acme", pdf, "liteparse")
    assert docling_id != liteparse_id
    assert len(docling_id) == 16
    assert len(liteparse_id) == 16


def test_given_same_inputs_when_hashed_twice_then_doc_id_stable(tmp_path: Path) -> None:
    pdf: Path = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF same bytes")
    assert Ids.document(" Acme ", pdf, " Docling ") == Ids.document("acme", pdf, "docling")


def test_given_same_index_when_kinds_differ_then_node_ids_differ() -> None:
    """A parent counter and a child counter both start at 0."""
    assert Ids.node("abc", 0, "p") != Ids.node("abc", 0, "c")


def test_given_kind_and_index_when_built_then_node_id_is_doc_kind_index() -> None:
    """The shape is relied on when reading a dumped chunk back."""
    assert Ids.node("abc", 7, "p") == "abc:p7"
    assert Ids.node("abc", 7, "c") == "abc:c7"
