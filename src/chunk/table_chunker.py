"""One table split into row groups that each stand alone as a retrievable chunk."""

from chunk.block_renderer import BlockRenderer
from chunk.greedy_packer import GreedyPacker
from chunk.table_headers import TableHeaders
from chunk.tokenizer import Tokenizer
from parse import TableBlock


class TableChunker:
    """Splits one table into row groups that each stand alone as a retrievable chunk."""

    @classmethod
    def texts(cls, b: TableBlock, max_tokens: int) -> list[str]:
        """Render one table as row groups that each repeat the caption and column names.

        A whole dense table in one chunk gives a single embedding for every metric it holds,
        which matches no individual metric well enough to retrieve.

        Args:
            b: The table block.
            max_tokens: Tokens a single row group may cost.

        Returns:
            One text per row group, or the whole rendered table when it holds no rows.
        """
        headers, rows = TableHeaders.split(b)
        if not rows:
            return [BlockRenderer.table(b)]
        width: int = max(len(headers), max(len(r) for r in rows))
        preamble: str = cls._preamble(b, headers, width)
        packer = GreedyPacker(preamble, max(max_tokens - Tokenizer.count(preamble), 1))
        for row in rows:
            packer.add(BlockRenderer.row_line(row, width))
        return packer.groups()

    @staticmethod
    def _preamble(b: TableBlock, headers: list[str], width: int) -> str:
        """The caption and column headers every row group repeats.

        Args:
            b: The table block, for its caption.
            headers: The column names.
            width: How many columns each row has.

        Returns:
            The preamble text, ending in a newline.
        """
        caption: str = f"**{b.caption.strip()}**\n\n" if b.caption.strip() else ""
        header_line: str = BlockRenderer.row_line(headers, width)
        sep_line: str = BlockRenderer.row_line(["---"] * width, width)
        return f"{caption}{header_line}\n{sep_line}\n"
