"""The vector index type is configuration, because switching it is a rebuild.

The index is derived from the stored vectors, so changing type costs a rebuild and
never a re-embedding, a schema change or a data migration. That only holds in
practice if the type is a setting rather than a literal in the code.
"""

from typing import Any

import pytest
from pytest_mock import MockerFixture

from peerdex.index._index import _ensure_vector_index, _vector_index_shape


def _index(mocker: MockerFixture, index_type: str, column: str = "vector") -> Any:
    """A stand-in for one LanceDB ``IndexConfig``.

    LanceDB reports the type in its own spelling - ``IvfPq``, not ``IVF_PQ`` - so
    tests must use that spelling or they will not catch a comparison that assumes
    the configured one.
    """
    index: Any = mocker.MagicMock()
    index.index_type = index_type
    index.columns = [column]
    return index


def _table(mocker: MockerFixture, rows: int = 4739, indices: list[Any] | None = None) -> Any:
    """A stand-in LanceDB table reporting ``rows`` rows of 1536-dim vectors."""
    field: Any = mocker.MagicMock()
    field.type.list_size = 1536
    tbl: Any = mocker.MagicMock()
    tbl.schema.field.return_value = field
    tbl.count_rows.return_value = rows
    tbl.list_indices.return_value = indices or []
    mocker.patch("peerdex.index._index.table", return_value=tbl)
    return tbl


def _configure(mocker: MockerFixture, vector_type: str) -> None:
    """Point the index settings at one LanceDB index type."""
    settings: Any = mocker.patch("peerdex.index._index.get_settings")
    settings.return_value.index.vector_type = vector_type


def test_given_a_configured_type_when_ensuring_then_that_type_is_built(
    mocker: MockerFixture,
) -> None:
    """Switching index type must not require a code change."""
    tbl: Any = _table(mocker)
    _configure(mocker, "IVF_HNSW_SQ")

    _ensure_vector_index("corporate")

    assert tbl.create_index.call_args.kwargs["index_type"] == "IVF_HNSW_SQ"


def test_given_the_default_type_when_ensuring_then_the_shape_is_derived_from_the_rows(
    mocker: MockerFixture,
) -> None:
    """A pair tuned on one corpus is wrong for the next, so both come from the data."""
    tbl: Any = _table(mocker, rows=4739)
    _configure(mocker, "IVF_PQ")

    _ensure_vector_index("corporate")

    kwargs: dict[str, Any] = tbl.create_index.call_args.kwargs
    assert kwargs["num_partitions"] == 68
    assert kwargs["num_sub_vectors"] == 96
    assert kwargs["vector_column_name"] == "vector"
    assert kwargs["metric"] == "cosine"


def test_given_an_unquantised_type_when_ensuring_then_no_sub_vectors_are_passed(
    mocker: MockerFixture,
) -> None:
    """`IVF_FLAT` stores vectors whole; sub-vectors are a quantisation parameter."""
    tbl: Any = _table(mocker)
    _configure(mocker, "IVF_FLAT")

    _ensure_vector_index("corporate")

    assert "num_sub_vectors" not in tbl.create_index.call_args.kwargs


def test_given_an_index_of_the_configured_type_when_ensuring_then_nothing_is_built(
    mocker: MockerFixture,
) -> None:
    """Ingest calls this every time, so it has to be a no-op once the index exists.

    LanceDB names the type ``IvfPq``. Comparing that against the configured
    ``IVF_PQ`` without normalising rebuilt the index on every single ingest -
    minutes of wasted work per document at production size.
    """
    tbl: Any = _table(mocker, indices=[_index(mocker, "IvfPq")])
    _configure(mocker, "IVF_PQ")

    _ensure_vector_index("corporate")

    tbl.create_index.assert_not_called()


def test_given_an_index_of_another_type_when_ensuring_then_it_is_rebuilt(
    mocker: MockerFixture,
) -> None:
    """Changing the setting has to take effect, or it is not really configuration."""
    tbl: Any = _table(mocker, indices=[_index(mocker, "IvfPq")])
    _configure(mocker, "IVF_HNSW_SQ")

    _ensure_vector_index("corporate")

    assert tbl.create_index.call_args.kwargs["index_type"] == "IVF_HNSW_SQ"


def test_given_only_a_full_text_index_when_ensuring_then_the_vector_index_is_built(
    mocker: MockerFixture,
) -> None:
    """The full-text index lives on another column and says nothing about vectors."""
    tbl: Any = _table(mocker, indices=[_index(mocker, "FTS", column="text")])
    _configure(mocker, "IVF_PQ")

    _ensure_vector_index("corporate")

    tbl.create_index.assert_called_once()


@pytest.mark.parametrize(
    ("rows", "expected_partitions"),
    [(1, 1), (100, 10), (4739, 68), (4_310_000, 2076), (100_000_000, 4096)],
)
def test_given_a_row_count_when_shaping_then_partitions_track_its_square_root(
    rows: int, expected_partitions: int
) -> None:
    """Partitions near the square root, capped so a huge table stays buildable."""
    partitions: int
    partitions, _ = _vector_index_shape(rows, 1536)

    assert partitions == expected_partitions
