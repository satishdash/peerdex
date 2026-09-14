"""Pure projection from a liteparse parse result onto contract blocks."""

from parse.contract import (
    Block,
    PageInfo,
)
from parse.liteparse.mappers.block_mapper import BlockMapper
from parse.liteparse.mappers.figure_mapper import FigureMapper
from parse.liteparse.mappers.heading_mapper import HeadingMapper
from parse.liteparse.mappers.list_item_mapper import ListItemMapper
from parse.liteparse.mappers.paragraph_mapper import ParagraphMapper
from parse.liteparse.mappers.table_mapper import TableMapper
from parse.liteparse.picture_gate import PictureGate
from parse.liteparse.projection_state import ProjectionState
from parse.liteparse.protocols.image_like import ImageLike
from parse.liteparse.protocols.page_like import PageLike
from parse.liteparse.protocols.parse_result_like import ParseResultLike


class LiteParseProjector:
    """Pure projection from a liteparse parse result onto contract blocks."""

    def __init__(self, gate: PictureGate) -> None:
        """Bind one mapper to each layout block kind.

        Args:
            gate: Decides which pictures are worth describing.
        """
        paragraph_mapper: ParagraphMapper = ParagraphMapper()
        table_mapper: TableMapper = TableMapper()
        self._mappers: dict[str, BlockMapper] = {
            "heading": HeadingMapper(),
            "paragraph": paragraph_mapper,
            "code": paragraph_mapper,
            "list_item": ListItemMapper(),
            "table": table_mapper,
            "grid_fallback": table_mapper,
            "figure": FigureMapper(gate),
        }

    def project(self, result: ParseResultLike) -> tuple[list[Block], list[PageInfo]]:
        """Walk pages 1..num_pages, mapping each block; unknown kinds are skipped.

        Args:
            result: The parser's raw result.

        Returns:
            The projected blocks and the pages they came from.
        """
        images: dict[str, ImageLike] = {image.id: image for image in result.images or []}
        state: ProjectionState = ProjectionState(images=images)
        pages: list[PageInfo] = []
        for page_num in range(1, result.num_pages + 1):
            page: PageLike | None = result.get_page(page_num)
            if page is None:
                continue
            pages.append(
                PageInfo(page_no=page.page_num, width=float(page.width), height=float(page.height))
            )
            self._project_page(page, state)
        return state.blocks, pages

    def _project_page(self, page: PageLike, state: ProjectionState) -> None:
        """Map every block on one page.

        Args:
            page: The page being projected.
            state: The accumulator this projection is building into.
        """
        state.begin_page(page)
        for block in page.blocks or []:
            mapper: BlockMapper | None = self._mappers.get(block.kind)
            if mapper is not None:
                mapper.map(block, state)
