"""Extractor registry: name resolution and the project default."""

import pytest

from peerdex.parse import DoclingExtractor, get_extractor


def test_given_no_name_when_extractor_requested_then_default_is_docling() -> None:
    """docling is the default: it keeps table row labels attached to their values."""
    assert isinstance(get_extractor(), DoclingExtractor)


def test_given_unknown_name_when_extractor_requested_then_rejected() -> None:
    """An unregistered name is refused rather than silently falling back."""
    with pytest.raises(ValueError, match="unknown extractor 'nope'"):
        get_extractor("nope")
