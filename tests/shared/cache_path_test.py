"""Cache paths must sit directly under the cache root, joined exactly once."""

from peerdex.shared.cache import chunk_debug_path, fs_and_root


def test_given_doc_id_when_debug_path_built_then_it_sits_directly_under_the_cache_root() -> None:
    """The root already is the cache dir, so any extra 'cache' segment writes outside it."""
    _, root = fs_and_root()

    assert chunk_debug_path("abc123") == f"{root.rstrip('/')}/chunks/abc123.md"
