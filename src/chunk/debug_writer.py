"""One document's chunks written to disk, so what was cut can be read back."""

from collections.abc import Iterable

from llama_index.core.schema import TextNode

from shared.cache import Cache


class DebugWriter:
    """Writes one document's chunks to disk, so what was cut can be read back."""

    @classmethod
    def write(cls, doc_id: str, nodes: Iterable[TextNode]) -> None:
        """Write the chunks, leaving an already written document alone.

        Args:
            doc_id: The document whose chunks these are.
            nodes: The chunks to write, in reading order.
        """
        fs, _root = Cache.fs_and_root()
        path = Cache.chunk_debug_path(doc_id)
        if fs.exists(path):
            return
        fs.makedirs(Cache.chunk_debug_dir(), exist_ok=True)
        with fs.open(path, "w") as handle:
            handle.write("\n---\n\n".join(cls._entry(node) for node in nodes))

    @staticmethod
    def _entry(node: TextNode) -> str:
        """One node as a readable entry.

        Args:
            node: The chunk to render.

        Returns:
            The heading, the rest of the metadata, and the text.
        """
        head: str = f"# {node.metadata.get('heading_path', 'root')}"
        rest: str = " | ".join(
            f"{k}={v}" for k, v in sorted(node.metadata.items()) if k not in ("heading_path",)
        )
        return f"{head} [{rest}]\n\n{node.text}"
