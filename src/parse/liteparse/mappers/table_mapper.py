"""``table`` / ``grid_fallback`` -> TableBlock; content-free tables dropped."""

from parse.contract import (
    TableBlock,
)
from parse.liteparse.mappers.block_mapper import BlockMapper
from parse.liteparse.projection_state import ProjectionState
from parse.liteparse.protocols.layout_block_like import LayoutBlockLike


class TableMapper(BlockMapper):
    """``table`` / ``grid_fallback`` -> TableBlock; content-free tables dropped."""

    def map(self, block: LayoutBlockLike, state: ProjectionState) -> None:
        """Append a table, dropping one whose cells are all empty.

        Args:
            block: The layout block being mapped.
            state: The accumulator this projection is building into.
        """
        headers: list[str] = [self.clean(cell.text) for cell in block.header or []]
        rows: list[list[str]] = [
            [self.clean(cell.text) for cell in row] for row in block.rows or []
        ]
        cells: list[str] = headers + [text for row in rows for text in row]
        if not any(cells):
            return
        state.blocks.append(
            TableBlock(
                kind="table",
                headers=headers,
                rows=rows,
                caption="",
                page_no=state.page_no,
                heading_path=state.headings.path(),
            )
        )
