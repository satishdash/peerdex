"""Filters must reach LanceDB as SQL, so the database does the narrowing."""

import pytest

from index import Predicates


def test_given_one_value_per_key_when_built_then_equality_per_key() -> None:
    """The common case: one company, one year, one extractor."""
    predicate = Predicates.attributes({"company": ("acme",), "year": (2025,)})

    assert predicate == "metadata.company = 'acme' AND metadata.year = 2025"


def test_given_several_values_when_built_then_in_clause() -> None:
    """Several values for one key mean OR within that key."""
    predicate = Predicates.attributes({"year": (2024, 2025)})

    assert predicate == "metadata.year IN (2024, 2025)"


def test_given_quote_in_value_when_built_then_it_is_escaped() -> None:
    """A company name carrying an apostrophe must not end the SQL string early."""
    predicate = Predicates.attributes({"company": ("o'neill",)})

    assert predicate == "metadata.company = 'o''neill'"


def test_given_boolean_when_built_then_sql_literal() -> None:
    """Booleans are SQL keywords, not quoted strings, and not 1/0."""
    assert Predicates.attributes({"is_table": (True,)}) == "metadata.is_table = true"


def test_given_unsafe_key_when_built_then_it_refuses() -> None:
    """Keys come from sidecars, so a crafted key must never reach the predicate."""
    with pytest.raises(ValueError, match="attribute key"):
        Predicates.attributes({"company'; DROP TABLE peer_nodes; --": ("acme",)})


def test_given_no_filters_when_built_then_empty() -> None:
    """No filters means no WHERE clause, not a malformed one."""
    assert Predicates.attributes({}) == ""
