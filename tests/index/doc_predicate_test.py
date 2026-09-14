"""The re-index delete predicate must target the key the chunker actually writes."""

from index import Predicates


def test_given_doc_id_when_predicate_built_then_it_targets_the_owned_key() -> None:
    """A predicate on LlamaIndex's reserved doc_id matches nothing, so re-index would duplicate."""
    assert Predicates.document("sha256-of-acme") == "metadata.source_doc_id = 'sha256-of-acme'"
