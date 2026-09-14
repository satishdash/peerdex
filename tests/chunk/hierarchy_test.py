"""Parent and child nodes must form a clean two-level tree.

A child that ends up as its own parent sends ``AutoMergingRetriever`` into an endless
merge loop, and a parent that does not list its children makes its ratio threshold
collapse to "always merge".
"""

from llama_index.core.schema import NodeRelationship, TextNode

from chunk import HierarchicalChunker
from parse import ExtractedDoc, PageInfo, ParagraphBlock, TableBlock
from shared.document_metadata import DocumentMetadata

HEADING: list[str] = ["Climate"]


def _doc() -> ExtractedDoc:
    return ExtractedDoc(
        blocks=[
            TableBlock(
                kind="table",
                headers=["metric", "2025"],
                rows=[["Scope 1 - Total", "62587"]],
                caption="GHG emissions",
                page_no=1,
                heading_path=HEADING,
            ),
            ParagraphBlock(
                kind="paragraph",
                text="Scope 1 emissions fell against a 2019 baseline across the estate.",
                page_no=1,
                heading_path=HEADING,
            ),
        ],
        pages=[PageInfo(page_no=1, width=612.0, height=792.0)],
        source_meta={},
    )


def _table(caption: str, label: str, value: str) -> TableBlock:
    return TableBlock(
        kind="table",
        headers=["metric", "2025"],
        rows=[[label, value]],
        caption=caption,
        page_no=1,
        heading_path=HEADING,
    )


def _two_table_doc() -> ExtractedDoc:
    return ExtractedDoc(
        blocks=[
            _table("GHG emissions", "Scope 1 - Total", "62587"),
            _table("Water use", "Municipal water", "1234"),
        ],
        pages=[PageInfo(page_no=1, width=612.0, height=792.0)],
        source_meta={},
    )


async def _chunk(doc: ExtractedDoc) -> tuple[list[TextNode], list[TextNode]]:
    meta = DocumentMetadata(
        company="acme", year=2025, source_uri="/docs/a.pdf", extractor="docling"
    )
    return await HierarchicalChunker().chunk(doc, doc_id="d1", metadata=meta)


async def _chunked() -> tuple[list[TextNode], list[TextNode]]:
    return await _chunk(_doc())


async def test_given_two_tables_in_one_section_when_chunked_then_parents_are_distinct() -> None:
    """One parent id per section let the second table overwrite the first in the docstore."""
    parents, children = await _chunk(_two_table_doc())

    assert len(parents) == 2
    assert len({p.node_id for p in parents}) == 2
    assert len(children) == 2

    for marker in ("62587", "1234"):
        owner = [p for p in parents if marker in p.text]
        assert len(owner) == 1
        kids = [
            c
            for c in children
            if (rel := c.relationships.get(NodeRelationship.PARENT)) is not None
            and rel.node_id == owner[0].node_id
        ]
        assert len(kids) == 1
        assert marker in kids[0].text


async def test_given_first_section_when_chunked_then_no_node_is_its_own_parent() -> None:
    """Section 0's parent and child 0 once shared an id, so the child parented itself."""
    parents, children = await _chunked()

    offenders = [
        c.node_id
        for c in [*parents, *children]
        if (rel := c.relationships.get(NodeRelationship.PARENT)) is not None
        and rel.node_id == c.node_id
    ]

    assert offenders == []


async def test_given_parents_and_children_when_chunked_then_ids_are_disjoint() -> None:
    """Parents and children are numbered by separate counters, so ids must not overlap."""
    parents, children = await _chunked()

    parent_ids = {p.node_id for p in parents}
    child_ids = {c.node_id for c in children}

    assert len(parent_ids) == len(parents)
    assert len(child_ids) == len(children)
    assert parent_ids & child_ids == set()


async def test_given_children_when_chunked_then_each_child_points_at_a_real_parent() -> None:
    """``parent_id`` is the only link that reaches the database, so it must resolve."""
    parents, children = await _chunked()

    parent_ids = {p.node_id for p in parents}
    pointed_at = {
        rel.node_id
        for c in children
        if (rel := c.relationships.get(NodeRelationship.PARENT)) is not None
    }

    assert pointed_at != set()
    assert pointed_at <= parent_ids
    assert pointed_at == parent_ids
