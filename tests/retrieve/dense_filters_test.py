"""Unit tests for the dense-filter projection of the shared retrieval predicate."""

from llama_index.core.vector_stores.types import FilterOperator, MetadataFilter, MetadataFilters

from peerdex.retrieve import HybridRetriever
from peerdex.shared.metadata import AttributeFilter


def test_given_attribute_filter_when_projected_then_dense_filters_mirror_pairs() -> None:
    filt: AttributeFilter = AttributeFilter("Globex", {"benchmark": True, "year": 2024})
    dense: MetadataFilters = HybridRetriever.dense_filters(filt)
    assert len(dense.filters) == 3
    by_key: dict[str, MetadataFilter] = {f.key: f for f in dense.filters}
    assert by_key["company"].value == "globex"
    assert by_key["benchmark"].value == 1
    assert by_key["year"].value == 2024
    assert all(f.operator == FilterOperator.EQ for f in dense.filters)


def test_given_company_only_filter_when_projected_then_single_filter() -> None:
    dense: MetadataFilters = HybridRetriever.dense_filters(AttributeFilter("acme"))
    assert len(dense.filters) == 1
    only: MetadataFilter = dense.filters[0]
    assert only.key == "company"
    assert only.value == "acme"
