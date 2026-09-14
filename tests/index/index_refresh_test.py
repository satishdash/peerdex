"""Newly ingested rows have embeddings but are not yet inside either index.

Both indexes are built once and then skipped, so every document after the first
left its rows outside them. LanceDB answers those rows by scanning, so results stay
correct while the cost quietly grows back to the unindexed one. Measured mid-ingest:
`indexed=4739 unindexed=2053` on both `text_idx` and `vector_idx`.
"""

from typing import Any

from pytest_mock import MockerFixture

from index import TableIndexes


def _index(mocker: MockerFixture, name: str, unindexed: int) -> Any:
    """A stand-in ``IndexConfig`` reporting how many rows it does not cover."""
    index: Any = mocker.MagicMock()
    index.name = name
    index.num_unindexed_rows = unindexed
    return index


def _table(mocker: MockerFixture, indices: list[Any]) -> Any:
    tbl: Any = mocker.MagicMock()
    tbl.list_indices.return_value = indices
    mocker.patch("index.vector_index.Tables.open", return_value=tbl)
    return tbl


def test_given_rows_outside_an_index_when_refreshing_then_the_table_is_optimised(
    mocker: MockerFixture,
) -> None:
    """Folding new rows in incrementally is the point; a full rebuild is the waste."""
    tbl: Any = _table(mocker, [_index(mocker, "vector_idx", 2053)])

    TableIndexes.refresh("corporate")

    tbl.optimize.assert_called_once()


def test_given_one_stale_index_of_several_when_refreshing_then_it_still_optimises(
    mocker: MockerFixture,
) -> None:
    """Full text and vector go stale independently, and either one is enough."""
    tbl: Any = _table(
        mocker,
        [_index(mocker, "text_idx", 0), _index(mocker, "vector_idx", 2053)],
    )

    TableIndexes.refresh("corporate")

    tbl.optimize.assert_called_once()


def test_given_every_row_indexed_when_refreshing_then_nothing_is_optimised(
    mocker: MockerFixture,
) -> None:
    """Ingest calls this every time, so a fully indexed table must cost nothing."""
    tbl: Any = _table(
        mocker,
        [_index(mocker, "text_idx", 0), _index(mocker, "vector_idx", 0)],
    )

    TableIndexes.refresh("corporate")

    tbl.optimize.assert_not_called()


def test_given_no_indexes_at_all_when_refreshing_then_nothing_is_optimised(
    mocker: MockerFixture,
) -> None:
    """Before the first index exists there is nothing to fold rows into."""
    tbl: Any = _table(mocker, [])

    TableIndexes.refresh("corporate")

    tbl.optimize.assert_not_called()
