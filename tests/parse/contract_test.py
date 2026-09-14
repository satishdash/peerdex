"""Every registered extractor honours both halves of the Extractor contract.

Callers pick an entry point and must not have to ask which one an extractor
implements. When one is missing, each call site invents its own fallback and the
harness can end up exercising a different path from production, which makes two
extractors incomparable for reasons that have nothing to do with parsing.
"""

import inspect

import pytest

from parse import ExtractorRegistry


@pytest.mark.parametrize("name", ExtractorRegistry.available())
def test_given_a_registered_extractor_when_inspected_then_both_entry_points_exist(
    name: str,
) -> None:
    """A sync `extract` and an awaitable `extract_async`, on every extractor."""
    extractor: object = ExtractorRegistry.create(name)

    assert callable(getattr(extractor, "extract", None))
    assert inspect.iscoroutinefunction(getattr(extractor, "extract_async", None))


@pytest.mark.parametrize("name", ExtractorRegistry.available())
def test_given_a_registered_extractor_when_inspected_then_it_names_itself(name: str) -> None:
    """`source_meta` provenance and the parse cache key both come from these."""
    extractor: object = ExtractorRegistry.create(name)

    assert getattr(extractor, "name", "") == name
    assert getattr(extractor, "version", "")
