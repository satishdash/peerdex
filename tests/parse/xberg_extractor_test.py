"""Projection of xberg's extracted document into the shared block contract."""

import io
from dataclasses import dataclass, field

import pytest
from PIL import Image

from parse import (
    HeadingBlock,
    ListBlock,
    ParagraphBlock,
    PictureBlock,
    TableBlock,
)
from parse.liteparse import PictureGate
from parse.xberg import HeadingRule, XbergProjector

_PAGE_WIDTH: float = 842.0
_PAGE_HEIGHT: float = 595.0


def _png(width: int = 8, height: int = 8) -> bytes:
    buffer: io.BytesIO = io.BytesIO()
    Image.new("RGB", (width, height), (120, 120, 120)).save(buffer, format="PNG")
    return buffer.getvalue()


@dataclass
class FakeBox:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class FakeImage:
    bounding_box: FakeBox
    data: bytes = b""
    page_number: int | None = 1
    caption: str = ""


@dataclass
class FakeMetadata:
    page_number: int | None = 1


@dataclass
class FakeElement:
    element_type: str
    text: str
    metadata: FakeMetadata = field(default_factory=FakeMetadata)


@dataclass
class FakeTable:
    cells: list[list[str]]
    page_number: int | None = 1
    markdown: str = ""


@dataclass
class FakePage:
    page_number: int = 1


@dataclass
class FakeDocument:
    elements: list[FakeElement] = field(default_factory=list)
    tables: list[FakeTable] = field(default_factory=list)
    pages: list[FakePage] = field(default_factory=list)
    images: list[FakeImage] = field(default_factory=list)


def _project(document: FakeDocument) -> list[object]:
    blocks, _pages = XbergProjector().project(document)
    return list(blocks)


def _full_page_box() -> FakeBox:
    return FakeBox(0.0, 0.0, _PAGE_WIDTH, _PAGE_HEIGHT)


def test_given_narrative_text_when_projected_then_paragraph_carries_its_page() -> None:
    """A page number from the element metadata reaches the block, never a zero default."""
    document: FakeDocument = FakeDocument(
        elements=[FakeElement("narrative_text", "Scope 1 rose this year.", FakeMetadata(7))]
    )

    blocks: list[object] = _project(document)

    assert len(blocks) == 1
    block: ParagraphBlock = blocks[0]
    assert isinstance(block, ParagraphBlock)
    assert block.text == "Scope 1 rose this year."
    assert block.page_no == 7


def test_given_native_table_when_projected_then_headers_split_from_rows() -> None:
    """Xberg reports tables natively, so no whitespace heuristic decides the grid."""
    document: FakeDocument = FakeDocument(
        tables=[FakeTable([["Metric", "2025"], ["Scope 1", "62,587"]], page_number=4)]
    )

    blocks: list[object] = _project(document)

    assert len(blocks) == 1
    table: TableBlock = blocks[0]
    assert isinstance(table, TableBlock)
    assert table.headers == ["Metric", "2025"]
    assert table.rows == [["Scope 1", "62,587"]]
    assert table.page_no == 4


def test_given_heading_shaped_text_when_projected_then_it_becomes_a_heading() -> None:
    """PDFs reach us as undifferentiated narrative text, so shape decides."""
    document: FakeDocument = FakeDocument(
        elements=[
            FakeElement("narrative_text", "ENVIRONMENTAL PERFORMANCE"),
            FakeElement("narrative_text", "Our emissions fell by a fifth over the period."),
        ]
    )

    blocks: list[object] = _project(document)

    assert len(blocks) == 2
    heading: HeadingBlock = blocks[0]
    assert isinstance(heading, HeadingBlock)
    assert heading.text == "ENVIRONMENTAL PERFORMANCE"
    assert heading.level == 1
    assert blocks[1].heading_path == ["ENVIRONMENTAL PERFORMANCE"]


def test_given_typed_elements_when_projected_then_each_kind_is_honoured() -> None:
    """Formats other than PDF emit real types; they must not go through the heuristic."""
    document: FakeDocument = FakeDocument(
        elements=[
            FakeElement("title", "Annual Report"),
            FakeElement("heading", "Governance"),
            FakeElement("list_item", "• Board independence"),
            FakeElement("list_item", "• Audit committee"),
        ]
    )

    blocks: list[object] = _project(document)

    assert [type(block).__name__ for block in blocks] == [
        "HeadingBlock",
        "HeadingBlock",
        "ListBlock",
    ]
    items: ListBlock = blocks[2]
    assert items.items == ["Board independence", "Audit committee"]


def test_given_page_elements_when_projected_then_every_page_is_reported() -> None:
    """The page list drives citation, so it must reflect the document, not the blocks."""
    document: FakeDocument = FakeDocument(pages=[FakePage(1), FakePage(2), FakePage(3)])

    _blocks, pages = XbergProjector().project(document)

    assert [page.page_no for page in pages] == [1, 2, 3]


def test_given_bulleted_narrative_text_when_projected_then_it_becomes_one_list() -> None:
    """Docling and liteparse both emit lists; the PDF path must not lose them to prose."""
    document: FakeDocument = FakeDocument(
        elements=[
            FakeElement("narrative_text", "• Board independence"),
            FakeElement("narrative_text", "• Audit committee"),
            FakeElement("narrative_text", "Ordinary prose follows the list."),
        ]
    )

    blocks: list[object] = _project(document)

    assert [type(block).__name__ for block in blocks] == ["ListBlock", "ParagraphBlock"]
    items: ListBlock = blocks[0]
    assert items.items == ["Board independence", "Audit committee"]


def test_given_a_page_sized_image_when_projected_then_a_picture_carries_its_bitmap() -> None:
    """The VLM stage needs a decoded image, so bytes must arrive as one."""
    document: FakeDocument = FakeDocument(
        images=[FakeImage(_full_page_box(), _png(), page_number=5)]
    )

    blocks: list[object] = _project(document)

    assert len(blocks) == 1
    picture: PictureBlock = blocks[0]
    assert isinstance(picture, PictureBlock)
    assert picture.page_no == 5
    assert picture.pil_image.size == (8, 8)
    assert picture.bbox_area_pct == pytest.approx(100.0)


def test_given_a_tiny_image_when_projected_then_the_gate_drops_it() -> None:
    """Icons and rules are not data, and describing them costs a model call each."""
    gate: PictureGate = PictureGate.from_settings()
    side: float = _PAGE_WIDTH * (gate.min_bbox_area_pct / 100.0) / 20.0
    middle: float = _PAGE_HEIGHT / 2.0
    document: FakeDocument = FakeDocument(
        images=[
            FakeImage(_full_page_box(), _png()),
            FakeImage(FakeBox(10.0, middle, 10.0 + side, middle + side), _png()),
        ]
    )

    blocks: list[object] = _project(document)

    assert len(blocks) == 1
    assert blocks[0].bbox_area_pct == pytest.approx(100.0)


def test_given_an_undecodable_image_when_projected_then_it_is_skipped() -> None:
    """A broken payload must not abort a whole document's parse."""
    document: FakeDocument = FakeDocument(images=[FakeImage(_full_page_box(), b"not an image")])

    assert _project(document) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ENVIRONMENTAL PERFORMANCE", 1),
        ("Our approach to water", 2),
        ("This sentence ends with a full stop.", 0),
        ("Revenue was 1,234,567 and 890,123 and 456", 0),
        ("A", 0),
        ("Total emissions:", 0),
    ],
)
def test_given_candidate_text_when_rule_applied_then_level_matches(
    text: str, expected: int
) -> None:
    """Zero means not a heading; 1 is a shouted section, 2 a title-cased one."""
    assert HeadingRule().level(text) == expected
