"""Unit tests for the liteparse extractor projection seam."""

from dataclasses import dataclass
from io import BytesIO

import pytest
from PIL import Image

from parse.contract import (
    ExtractedDoc,
    HeadingBlock,
    ListBlock,
    PageInfo,
    ParagraphBlock,
    PictureBlock,
    TableBlock,
)
from parse.liteparse import LiteParseExtractor, PictureGate


@dataclass
class StubRect:
    x: float
    y: float
    width: float
    height: float


@dataclass
class StubCell:
    text: str


@dataclass
class StubBlock:
    kind: str
    text: str | None = None
    level: int | None = None
    ordered: bool | None = None
    header: list[StubCell] | None = None
    rows: list[list[StubCell]] | None = None
    id: str | None = None
    bbox: StubRect | None = None


@dataclass
class StubPage:
    page_num: int
    width: float = 612.0
    height: float = 792.0
    blocks: list[StubBlock] | None = None


@dataclass
class StubImage:
    id: str
    bytes: bytes


class StubResult:
    def __init__(self, pages: list[StubPage], images: list[StubImage] | None = None) -> None:
        self._pages: dict[int, StubPage] = {page.page_num: page for page in pages}
        self.num_pages: int = max(self._pages, default=0)
        self.images: list[StubImage] | None = images

    def get_page(self, page_num: int) -> StubPage | None:
        return self._pages.get(page_num)


def png_bytes(width: int = 4, height: int = 4) -> bytes:
    buffer: BytesIO = BytesIO()
    Image.new("RGB", (width, height), "red").save(buffer, format="PNG")
    return buffer.getvalue()


def project(pages: list[StubPage], images: list[StubImage] | None = None) -> ExtractedDoc:
    gate: PictureGate = PictureGate(min_bbox_area_pct=1.5, skip_header_footer_band_pct=8.0)
    return LiteParseExtractor(gate=gate).project(StubResult(pages, images))


def test_given_mixed_heading_levels_when_projected_then_paths_track_document_stack() -> None:
    doc: ExtractedDoc = project(
        [
            StubPage(
                1,
                blocks=[
                    StubBlock("heading", text="A", level=1),
                    StubBlock("heading", text="B", level=2),
                    StubBlock("heading", text="E", level=3),
                    StubBlock("heading", text="C", level=2),
                    StubBlock("heading", text="D", level=1),
                ],
            ),
            StubPage(2, blocks=[StubBlock("paragraph", text="body")]),
        ]
    )
    assert len(doc.blocks) == 6
    assert all(isinstance(block, HeadingBlock) for block in doc.blocks[:5])
    assert [block.heading_path for block in doc.blocks] == [
        [],
        ["A"],
        ["A", "B"],
        ["A"],
        [],
        ["D"],
    ]
    body: ParagraphBlock = doc.blocks[5]
    assert isinstance(body, ParagraphBlock)
    assert body.text == "body"
    assert body.page_no == 2


def test_given_blank_heading_when_projected_then_dropped_and_stack_unchanged() -> None:
    doc: ExtractedDoc = project(
        [
            StubPage(
                1,
                blocks=[
                    StubBlock("heading", text="A", level=1),
                    StubBlock("heading", text="\x06 ", level=2),
                    StubBlock("paragraph", text="body"),
                ],
            )
        ]
    )
    assert len(doc.blocks) == 2
    assert doc.blocks[1].heading_path == ["A"]


@pytest.mark.parametrize("kind", ["paragraph", "code"])
@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ("GRI 3: Material Topics 2021\x06", "GRI 3: Material Topics 2021"),
        ("a\tb\nc\x06\x07", "a\tb\nc"),
        ("  padded  ", "padded"),
    ],
)
def test_given_text_block_when_projected_then_paragraph_block_with_clean_text(
    kind: str, raw: str, cleaned: str
) -> None:
    doc: ExtractedDoc = project([StubPage(1, blocks=[StubBlock(kind, text=raw)])])
    assert len(doc.blocks) == 1
    block: ParagraphBlock = doc.blocks[0]
    assert isinstance(block, ParagraphBlock)
    assert block.text == cleaned
    assert block.page_no == 1
    assert block.heading_path == []


@pytest.mark.parametrize("kind", ["paragraph", "code", "list_item", "heading"])
@pytest.mark.parametrize("raw", [None, "", "   ", "\x06\x01 "])
def test_given_empty_text_when_projected_then_dropped(kind: str, raw: str | None) -> None:
    doc: ExtractedDoc = project([StubPage(1, blocks=[StubBlock(kind, text=raw, level=1)])])
    assert doc.blocks == []


def test_given_consecutive_list_items_when_projected_then_folded_in_order() -> None:
    doc: ExtractedDoc = project(
        [
            StubPage(
                1,
                blocks=[
                    StubBlock("list_item", text="one\x06", ordered=False),
                    StubBlock("list_item", text="two", ordered=False),
                    StubBlock("list_item", text="three", ordered=False),
                ],
            )
        ]
    )
    assert len(doc.blocks) == 1
    block: ListBlock = doc.blocks[0]
    assert isinstance(block, ListBlock)
    assert block.items == ["one", "two", "three"]
    assert block.ordered is False
    assert block.page_no == 1


def test_given_ordered_flip_when_projected_then_new_list_block() -> None:
    doc: ExtractedDoc = project(
        [
            StubPage(
                1,
                blocks=[
                    StubBlock("list_item", text="a", ordered=False),
                    StubBlock("list_item", text="b", ordered=False),
                    StubBlock("list_item", text="c", ordered=True),
                ],
            )
        ]
    )
    assert len(doc.blocks) == 2
    assert [block.items for block in doc.blocks] == [["a", "b"], ["c"]]
    assert [block.ordered for block in doc.blocks] == [False, True]


def test_given_page_boundary_when_projected_then_new_list_block() -> None:
    doc: ExtractedDoc = project(
        [
            StubPage(1, blocks=[StubBlock("list_item", text="a", ordered=False)]),
            StubPage(2, blocks=[StubBlock("list_item", text="b", ordered=False)]),
        ]
    )
    assert len(doc.blocks) == 2
    assert [block.page_no for block in doc.blocks] == [1, 2]
    assert [block.items for block in doc.blocks] == [["a"], ["b"]]


def test_given_heading_between_list_items_when_projected_then_new_list_block() -> None:
    doc: ExtractedDoc = project(
        [
            StubPage(
                1,
                blocks=[
                    StubBlock("list_item", text="a", ordered=False),
                    StubBlock("heading", text="H", level=1),
                    StubBlock("list_item", text="b", ordered=False),
                ],
            )
        ]
    )
    assert len(doc.blocks) == 3
    first: ListBlock = doc.blocks[0]
    last: ListBlock = doc.blocks[2]
    assert isinstance(first, ListBlock)
    assert isinstance(doc.blocks[1], HeadingBlock)
    assert isinstance(last, ListBlock)
    assert first.items == ["a"]
    assert first.heading_path == []
    assert last.items == ["b"]
    assert last.heading_path == ["H"]


def test_given_table_with_header_row_when_projected_then_headers_and_rows_cleaned() -> None:
    doc: ExtractedDoc = project(
        [
            StubPage(
                1,
                blocks=[
                    StubBlock(
                        "table",
                        header=[StubCell("Col A\x06"), StubCell("Col B")],
                        rows=[
                            [StubCell("1\x06"), StubCell("2")],
                            [StubCell("3"), StubCell("4")],
                        ],
                    )
                ],
            )
        ]
    )
    assert len(doc.blocks) == 1
    block: TableBlock = doc.blocks[0]
    assert isinstance(block, TableBlock)
    assert block.headers == ["Col A", "Col B"]
    assert block.rows == [["1", "2"], ["3", "4"]]
    assert block.caption == ""
    assert block.page_no == 1


@pytest.mark.parametrize("kind", ["table", "grid_fallback"])
def test_given_headerless_table_when_projected_then_empty_headers(kind: str) -> None:
    doc: ExtractedDoc = project(
        [StubPage(1, blocks=[StubBlock(kind, header=None, rows=[[StubCell("x")]])])]
    )
    assert len(doc.blocks) == 1
    block: TableBlock = doc.blocks[0]
    assert isinstance(block, TableBlock)
    assert block.headers == []
    assert block.rows == [["x"]]


@pytest.mark.parametrize("kind", ["table", "grid_fallback"])
def test_given_content_free_table_when_projected_then_dropped(kind: str) -> None:
    doc: ExtractedDoc = project(
        [
            StubPage(
                1,
                blocks=[
                    StubBlock(kind, header=None, rows=[[StubCell(""), StubCell("\x06 ")]]),
                    StubBlock(kind, header=None, rows=None),
                ],
            )
        ]
    )
    assert doc.blocks == []


def test_given_mid_page_large_figure_when_projected_then_picture_block() -> None:
    doc: ExtractedDoc = project(
        [
            StubPage(
                1,
                blocks=[StubBlock("figure", id="p1_1", bbox=StubRect(100.0, 300.0, 200.0, 200.0))],
            )
        ],
        [StubImage("p1_1", png_bytes())],
    )
    assert len(doc.blocks) == 1
    block: PictureBlock = doc.blocks[0]
    assert isinstance(block, PictureBlock)
    assert block.bbox_area_pct == 100.0 * (200.0 * 200.0) / (612.0 * 792.0)
    assert block.pil_image.size == (4, 4)
    assert block.pil_image.mode == "RGB"
    assert block.self_ref == "p1_1"
    assert block.page_no == 1


@pytest.mark.parametrize(
    ("bbox", "image"),
    [
        pytest.param(
            StubRect(100.0, 300.0, 50.0, 50.0),
            StubImage("p1_1", png_bytes()),
            id="below-min-area",
        ),
        pytest.param(
            StubRect(0.0, 10.0, 600.0, 40.0),
            StubImage("p1_1", png_bytes()),
            id="inside-top-band",
        ),
        pytest.param(
            StubRect(0.0, 740.0, 600.0, 40.0),
            StubImage("p1_1", png_bytes()),
            id="inside-bottom-band",
        ),
        pytest.param(
            StubRect(100.0, 300.0, 200.0, 200.0),
            StubImage("p9_9", png_bytes()),
            id="no-matching-image",
        ),
        pytest.param(
            StubRect(100.0, 300.0, 200.0, 200.0),
            StubImage("p1_1", b"not an image"),
            id="undecodable-bytes",
        ),
    ],
)
def test_given_gated_figure_when_projected_then_dropped(bbox: StubRect, image: StubImage) -> None:
    doc: ExtractedDoc = project(
        [StubPage(1, blocks=[StubBlock("figure", id="p1_1", bbox=bbox)])], [image]
    )
    assert doc.blocks == []


@pytest.mark.parametrize("kind", ["rule", "hologram"])
def test_given_unmapped_kind_when_projected_then_skipped(kind: str) -> None:
    doc: ExtractedDoc = project([StubPage(1, blocks=[StubBlock(kind)])])
    assert doc.blocks == []


def test_given_pages_when_projected_then_page_info_and_source_meta() -> None:
    doc: ExtractedDoc = project(
        [
            StubPage(1, width=612.0, height=792.0, blocks=None),
            StubPage(2, width=595.0, height=842.0, blocks=[]),
        ]
    )
    assert doc.pages == [PageInfo(1, 612.0, 792.0), PageInfo(2, 595.0, 842.0)]
    assert doc.blocks == []
    assert doc.source_meta["extractor_name"] == "liteparse"
    assert doc.source_meta["extractor_version"] == LiteParseExtractor.version
    assert doc.source_meta["options"] == {
        "extract_blocks": True,
        "extract_images": True,
        "ocr_enabled": True,
        "min_bbox_area_pct": 1.5,
        "skip_header_footer_band_pct": 8.0,
    }
