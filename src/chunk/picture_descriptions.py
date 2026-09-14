"""A document's figures described through the vision model, in one batch."""

from chunk.figure_renderer import FigureRenderer
from chunk.pending_node import PendingNode
from parse import PictureBlock
from shared.clients import Clients
from vlm import OpenAIPictureDescriber, PictureRef


class PictureDescriptions:
    """Describes a document's figures through the vision model, in one batch."""

    @classmethod
    async def of(cls, placed: list[tuple[int, PictureBlock]], doc_id: str) -> list[PendingNode]:
        """Describe every picture, each tagged with the section it was found in.

        Args:
            placed: Each picture with the index of the section holding it.
            doc_id: The document being described, for the description cache.

        Returns:
            One pending node per figure the model described, dropping those it did not.
        """
        describer = OpenAIPictureDescriber(Clients.openai_async())
        results = await describer.describe([cls._ref(pic) for _, pic in placed], doc_id=doc_id)
        return [
            cls._pending(sec_idx, pic, result)
            for (sec_idx, pic), result in zip(placed, results, strict=True)
            if result
        ]

    @staticmethod
    def _ref(pic: PictureBlock) -> PictureRef:
        """One picture as the reference the describer takes.

        Args:
            pic: The picture block, carrying its cut-out image.

        Returns:
            The reference, carrying the cut-out image itself.
        """
        return PictureRef(
            pil_image=pic.pil_image,
            page_no=pic.page_no,
            bbox_area_pct=pic.bbox_area_pct,
            heading_path=pic.heading_path,
            self_ref=pic.self_ref,
        )

    @staticmethod
    def _pending(sec_idx: int, pic: PictureBlock, result: dict) -> PendingNode:
        """One described figure, held until its section is chunked.

        Args:
            sec_idx: Index of the section the picture was found in.
            pic: The picture block.
            result: The description returned by the vision model.

        Returns:
            The pending node, its text already rendered.
        """
        return PendingNode(
            text=FigureRenderer.text(pic.page_no, pic.heading_path, result),
            heading_path=list(pic.heading_path),
            page_no=pic.page_no,
            sec_idx=sec_idx,
        )
