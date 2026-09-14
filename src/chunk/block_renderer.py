"""Parsed blocks rendered as the GFM text a chunk carries."""

from parse import ListBlock, ParagraphBlock, TableBlock


class BlockRenderer:
    """Renders parsed blocks as the GFM text a chunk carries."""

    @classmethod
    def heading_prefix(cls, heading_path: list[str]) -> str:
        """The heading breadcrumb prepended to a prose chunk.

        Args:
            heading_path: The ancestor headings, outermost first.

        Returns:
            The rendered prefix, empty at the document root.
        """
        if not heading_path:
            return ""
        return "## " + " > ".join(heading_path) + "\n\n"

    @classmethod
    def paragraph(cls, b: ParagraphBlock) -> str:
        """One paragraph as plain text.

        Args:
            b: The paragraph block.

        Returns:
            The paragraph text, trimmed.
        """
        return b.text.strip()

    @classmethod
    def bullets(cls, b: ListBlock) -> str:
        """One list as GFM bullets, blank items dropped.

        Args:
            b: The list block.

        Returns:
            The rendered list.
        """
        bullet: str = "1. " if b.ordered else "- "
        return "\n".join(f"{bullet}{item.strip()}" for item in b.items if item.strip())

    @classmethod
    def table(cls, b: TableBlock) -> str:
        """One whole table as a captioned GFM table.

        Args:
            b: The table block.

        Returns:
            The rendered table, or the caption alone when the table has no rows.
        """
        caption: str = f"**{b.caption.strip()}**\n\n" if b.caption.strip() else ""
        if not b.rows:
            return caption.rstrip()
        headers: list[str] = b.headers or [f"col{i}" for i in range(len(b.rows[0]))]
        width: int = len(headers)
        lines: list[str] = [
            cls.row_line(headers, width),
            cls.row_line(["---"] * width, width),
            *(cls.row_line(row, width) for row in b.rows),
        ]
        return caption + "\n".join(lines)

    @classmethod
    def row_line(cls, cells: list[str], width: int) -> str:
        """One table row padded or truncated to a fixed column count.

        Args:
            cells: The cells of the row.
            width: How many columns the row must have.

        Returns:
            The rendered row.
        """
        padded: list[str] = [*cells, *[""] * (width - len(cells))][:width]
        return "| " + " | ".join(cls._cell(c) for c in padded) + " |"

    @staticmethod
    def _cell(s: str) -> str:
        """One cell with newlines flattened and pipes escaped.

        Args:
            s: The raw cell text.

        Returns:
            The cell text, never empty.
        """
        s = (s or "").replace("\n", " ").replace("|", "\\|").strip()
        return s or " "
