"""Document identity must survive the vector store's metadata serialization."""

from llama_index.core.schema import TextNode
from llama_index.core.vector_stores.utils import node_to_metadata_dict

from peerdex.chunk import HierarchicalChunker
from peerdex.parse import ExtractedDoc, PageInfo, ParagraphBlock, TableBlock
from peerdex.shared.metadata import DocumentMetadata


def _extracted_doc() -> ExtractedDoc:
    return ExtractedDoc(
        blocks=[
            ParagraphBlock(
                kind="paragraph", text="Revenue was 100 MEUR.", page_no=1, heading_path=[]
            ),
            TableBlock(
                kind="table",
                headers=["metric", "value"],
                rows=[["revenue", "100"]],
                caption="",
                page_no=1,
                heading_path=[],
            ),
        ],
        pages=[PageInfo(page_no=1, width=612.0, height=792.0)],
        source_meta={},
    )


async def _children(doc_id: str) -> list[TextNode]:
    metadata: DocumentMetadata = DocumentMetadata(
        company="acme", year=2025, source_uri="/docs/acme.pdf", extractor="liteparse"
    )
    _, children = await HierarchicalChunker().chunk(
        _extracted_doc(), doc_id=doc_id, metadata=metadata
    )
    return children


async def test_given_chunked_nodes_when_stored_then_every_node_carries_the_document_hash() -> None:
    """Deleting a document's rows needs the hash on every row, under a key we own."""
    children = await _children("sha256-of-acme")

    assert len(children) == 2
    assert [n.metadata["source_doc_id"] for n in children] == ["sha256-of-acme"] * 2


async def test_given_reserved_key_collision_when_serialized_then_our_hash_survives() -> None:
    """LlamaIndex reserves doc_id and overwrites it with ref_doc_id, so ours lives elsewhere."""
    node = (await _children("sha256-of-acme"))[0]

    flat = node_to_metadata_dict(node, remove_text=False, flat_metadata=True)

    assert flat["source_doc_id"] == "sha256-of-acme"
    assert flat["doc_id"] == "None"
