"""Unit tests for the dense-filter projection of the shared retrieval predicate."""

import pytest
from llama_index.core.vector_stores.types import FilterCondition, FilterOperator, MetadataFilters

from peerdex.retrieve import HybridRetriever
from peerdex.shared.metadata import AttributeFilter, Scalar


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        pytest.param(None, [("company", "acme", FilterOperator.EQ)], id="company-only"),
        pytest.param(
            {"benchmark": True, "year": 2024},
            [
                ("company", "acme", FilterOperator.EQ),
                ("benchmark", 1, FilterOperator.EQ),
                ("year", 2024, FilterOperator.EQ),
            ],
            id="single-values-stay-eq",
        ),
        pytest.param(
            {"year": [2023, 2024], "region": "emea", "benchmark": [True, False]},
            [
                ("company", "acme", FilterOperator.EQ),
                ("year", [2023, 2024], FilterOperator.IN),
                ("region", "emea", FilterOperator.EQ),
                ("benchmark", [1, 0], FilterOperator.IN),
            ],
            id="multi-values-become-in",
        ),
    ],
)
def test_given_attribute_filter_when_projected_then_dense_filters_mirror_pairs(
    attributes: dict[str, Scalar | list[Scalar]] | None,
    expected: list[tuple[str, Scalar | list[Scalar], FilterOperator]],
) -> None:
    dense: MetadataFilters = HybridRetriever.dense_filters(AttributeFilter("Acme", attributes))
    assert dense.condition == FilterCondition.AND
    assert [(f.key, f.value, f.operator) for f in dense.filters] == expected
