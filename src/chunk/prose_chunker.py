"""A section's prose packed into chunks that each fit a parent node's token budget."""

from chunk.block_renderer import BlockRenderer
from chunk.greedy_packer import GreedyPacker
from chunk.tokenizer import Tokenizer
from parse import ListBlock, ParagraphBlock


class ProseChunker:
    """Packs a section's prose into chunks that each fit a parent node's token budget."""

    @classmethod
    def texts(
        cls,
        heading_path: list[str],
        blocks: list[ParagraphBlock | ListBlock],
        max_tokens: int,
    ) -> list[str]:
        """Greedy-packs paragraphs and lists into GFM chunks.

        Args:
            heading_path: The ancestor headings, outermost first.
            blocks: The section's paragraphs and lists, in reading order.
            max_tokens: Tokens a single chunk may cost.

        Returns:
            One text per chunk, each opening with the heading path.
        """
        prefix: str = BlockRenderer.heading_prefix(heading_path)
        prefix_tokens: int = Tokenizer.count(prefix)
        packer = GreedyPacker(prefix, max_tokens - prefix_tokens, carryover=prefix_tokens)
        for b in blocks:
            packer.add(cls._rendered(b))
        return packer.groups()

    @staticmethod
    def _rendered(b: ParagraphBlock | ListBlock) -> str:
        """One prose block as the GFM text a chunk carries.

        Args:
            b: The paragraph or list block.

        Returns:
            The rendered paragraph or bullet list.
        """
        if isinstance(b, ParagraphBlock):
            return BlockRenderer.paragraph(b)
        return BlockRenderer.bullets(b)
