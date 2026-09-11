"""Parent nodes belong in the database, not in a JSON file rewritten per ingest."""

from typing import Any

import pytest
from llama_index.core.schema import TextNode
from pytest_mock import MockerFixture

from peerdex.index import ParentStore


def _db(mocker: MockerFixture, existing: list[str]) -> tuple[Any, Any]:
    tbl = mocker.MagicMock()
    db = mocker.MagicMock()
    db.table_names.return_value = existing
    db.open_table.return_value = tbl
    db.create_table.return_value = tbl
    mocker.patch("peerdex.index._parents.lancedb.connect", return_value=db)
    return db, tbl


def _node(node_id: str, text: str = "| Scope 1 | 62,587 |") -> TextNode:
    return TextNode(id_=node_id, text=text, metadata={"source_doc_id": "d1", "is_parent": True})


def test_given_parents_when_stored_then_they_land_in_the_domains_parent_table(
    mocker: MockerFixture,
) -> None:
    """A domain owns its parents exactly as it owns its children."""
    db, tbl = _db(mocker, ["corporate", "corporate_parents"])

    stored: int = ParentStore("corporate").put("d1", [_node("d1:p0"), _node("d1:p1")])

    db.open_table.assert_called_once_with("corporate_parents")
    assert stored == 2
    rows: list[dict[str, Any]] = tbl.add.call_args.args[0]
    assert [row["id"] for row in rows] == ["d1:p0", "d1:p1"]
    assert rows[0]["text"] == "| Scope 1 | 62,587 |"
    assert rows[0]["metadata"]["source_doc_id"] == "d1"


def test_given_no_parent_table_yet_when_storing_then_it_is_created(
    mocker: MockerFixture,
) -> None:
    """The first ingest of a domain must not have to be preceded by a migration."""
    db, _ = _db(mocker, ["corporate"])

    ParentStore("corporate").put("d1", [_node("d1:p0")])

    db.create_table.assert_called_once()
    assert db.create_table.call_args.args[0] == "corporate_parents"


def test_given_a_document_reingested_when_storing_then_its_old_parents_go_first(
    mocker: MockerFixture,
) -> None:
    """Re-indexing a file replaces it. Parents that outlive their document are orphans.

    The predicate is the children's own, so parents and children can never be cleared
    by different rules: LlamaIndex overwrites ``doc_id``, hence ``source_doc_id``.
    """
    _, tbl = _db(mocker, ["corporate", "corporate_parents"])

    ParentStore("corporate").put("d1", [_node("d1:p0")])

    tbl.delete.assert_called_once_with("metadata.source_doc_id = 'd1'")


def test_given_no_parents_when_storing_then_the_database_is_left_alone(
    mocker: MockerFixture,
) -> None:
    """A document with no parent sections must not create an empty table."""
    db, tbl = _db(mocker, ["corporate"])

    assert ParentStore("corporate").put("d1", []) == 0
    db.create_table.assert_not_called()
    tbl.add.assert_not_called()


@pytest.mark.parametrize("domain", ["corporate", "invoices"])
def test_given_a_domain_when_naming_the_table_then_it_is_derived_from_it(domain: str) -> None:
    """Two domains never share a parent table, for the same reason they never share a table."""
    assert ParentStore(domain).table_name == f"{domain}_parents"
