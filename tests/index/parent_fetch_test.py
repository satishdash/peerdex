"""Escalation fetches a parent by id, so the id must round-trip through the table."""

from typing import Any

import pytest
from llama_index.core.schema import TextNode
from pytest_mock import MockerFixture

from index import ParentStore


def _node(node_id: str, text: str) -> TextNode:
    return TextNode(id_=node_id, text=text, metadata={"source_doc_id": "d1", "page_no": 7})


@pytest.fixture
def store(tmp_path: Any, mocker: MockerFixture) -> ParentStore:
    """A store backed by a real LanceDB under tmp_path.

    Returns:
        The store, pointed at an empty database.
    """
    settings: Any = mocker.patch("index.parent_store.get_settings")
    settings.return_value.storage.lancedb_uri = str(tmp_path / "db")
    mocker.patch("index.predicates.Predicates.document", side_effect=lambda d: f"id != '{d}-none'")
    return ParentStore("corporate")


def test_given_stored_parents_when_fetched_by_id_then_each_comes_back(store: ParentStore) -> None:
    """The escalation holds only a parent_id, so lookup is by id alone."""
    store.put("d1", [_node("d1:p0", "first parent"), _node("d1:p1", "second parent")])

    found = store.get(["d1:p1"])

    assert len(found) == 1
    assert found["d1:p1"].text == "second parent"
    assert found["d1:p1"].metadata["page_no"] == 7


def test_given_several_ids_when_fetched_then_all_are_returned(store: ParentStore) -> None:
    """A refused answer can cite several passages, so several parents are fetched at once."""
    store.put("d1", [_node("d1:p0", "a"), _node("d1:p1", "b"), _node("d1:p2", "c")])

    found = store.get(["d1:p0", "d1:p2"])

    assert sorted(found) == ["d1:p0", "d1:p2"]
    assert [found[i].text for i in ("d1:p0", "d1:p2")] == ["a", "c"]


def test_given_unknown_id_when_fetched_then_it_is_absent(store: ParentStore) -> None:
    """A figure in a section with no parent carries an empty id, so misses must not raise."""
    store.put("d1", [_node("d1:p0", "a")])

    assert store.get(["d1:p9"]) == {}


def test_given_no_ids_when_fetched_then_the_table_is_not_touched(store: ParentStore) -> None:
    """Escalation with nothing to fetch must cost no query."""
    assert store.get([]) == {}


def test_given_a_missing_table_when_fetched_then_it_is_empty(store: ParentStore) -> None:
    """A domain ingested before parents existed has no table; that is a miss, not a crash."""
    assert store.get(["d1:p0"]) == {}
