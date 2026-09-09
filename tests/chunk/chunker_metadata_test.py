"""Unit tests for node metadata merging and embedding hygiene in the chunker."""

from llama_index.core.schema import TextNode

from peerdex.chunk import HierarchicalChunker
from peerdex.parse import ExtractedDoc, HeadingBlock, PageInfo, ParagraphBlock, TableBlock
from peerdex.shared.metadata import DocumentMetadata
from peerdex.shared.prompts import PROMPTS

EXPECTED_EXCLUDED: list[str] = [
    "bucket_key",
    "extractor",
    "idx",
    "is_parent",
    "prompt_version",
    "source_doc_id",
    "source_uri",
    "url",
]


def _extracted_doc() -> ExtractedDoc:
    return ExtractedDoc(
        blocks=[
            HeadingBlock(kind="heading", level=1, text="Results", page_no=1, heading_path=[]),
            ParagraphBlock(
                kind="paragraph",
                text="Revenue was 100 MEUR.",
                page_no=1,
                heading_path=["Results"],
            ),
            TableBlock(
                kind="table",
                headers=["metric", "value"],
                rows=[["revenue", "100"]],
                caption="",
                page_no=1,
                heading_path=["Results"],
            ),
        ],
        pages=[PageInfo(page_no=1, width=612.0, height=792.0)],
        source_meta={},
    )


async def test_given_attributes_when_chunked_then_nodes_carry_merged_metadata() -> None:
    metadata: DocumentMetadata = DocumentMetadata(
        company=" Acme ",
        year=2025,
        source_uri="/docs/acme.pdf",
        extractor="liteparse",
        attributes={
            "title": "Data Index",
            "benchmark": True,
            "bucket_key": "Acme/a.pdf",
            "url": "https://x",
        },
    )
    parents, children = await HierarchicalChunker().chunk(
        _extracted_doc(), doc_id="d1", metadata=metadata
    )
    assert len(parents) == 2
    assert len(children) == 2
    table_child: TextNode = children[0]
    assert table_child.metadata == {
        "source_doc_id": "d1",
        "company": "acme",
        "year": 2025,
        "page_no": 1,
        "heading_path": "Results",
        "is_figure": False,
        "is_table": True,
        "is_parent": False,
        "idx": 0,
        "source_uri": "/docs/acme.pdf",
        "prompt_version": PROMPTS.prompt_version,
        "extractor": "liteparse",
        "title": "Data Index",
        "benchmark": 1,
        "bucket_key": "Acme/a.pdf",
        "url": "https://x",
    }
    prose_child: TextNode = children[1]
    assert prose_child.metadata["is_table"] is False
    assert prose_child.metadata["benchmark"] == 1
    assert prose_child.metadata["idx"] == 1
    for node in [*parents, *children]:
        assert node.excluded_embed_metadata_keys == EXPECTED_EXCLUDED
        assert node.excluded_llm_metadata_keys == EXPECTED_EXCLUDED


async def test_given_no_attributes_when_chunked_then_fixed_keys_only() -> None:
    metadata: DocumentMetadata = DocumentMetadata(
        company="acme", year=2024, source_uri="/docs/b.pdf", extractor="docling"
    )
    _, children = await HierarchicalChunker().chunk(
        _extracted_doc(), doc_id="d2", metadata=metadata
    )
    assert len(children) == 2
    assert sorted(children[0].metadata) == [
        "company",
        "extractor",
        "heading_path",
        "idx",
        "is_figure",
        "is_parent",
        "is_table",
        "page_no",
        "prompt_version",
        "source_doc_id",
        "source_uri",
        "year",
    ]
    assert children[0].metadata["year"] == 2024
