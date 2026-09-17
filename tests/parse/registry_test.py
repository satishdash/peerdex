"""Extractor registry: name resolution."""

import pytest

from parse import ExtractorRegistry


def test_given_unknown_name_when_extractor_requested_then_rejected() -> None:
    """An unregistered name is refused rather than silently falling back."""
    with pytest.raises(ValueError, match="unknown extractor 'nope'"):
        ExtractorRegistry.create("nope")
