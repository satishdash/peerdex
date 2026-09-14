"""An ODL table element projected onto a TableBlock."""

from parse.contract import (
    TableBlock,
)


class Table:
    """An ODL table element projected onto a TableBlock."""

    @classmethod
    def block(cls, el: dict, heading_path: list[str]) -> TableBlock | None:
        """Build a table block, or None when the element carries no rows.

        Args:
            el: The element being read.
            heading_path: The ancestor headings, outermost first.

        Returns:
            The table block, or None when the element carries no rows.
        """
        rows_raw: list[dict] = el.get("rows", [])
        if not rows_raw:
            return None
        headers, rows = cls._split(cls._grid(rows_raw, el.get("number of columns", 0)))
        return TableBlock(
            kind="table",
            headers=headers,
            rows=rows,
            caption="",
            page_no=el.get("page number", 0),
            heading_path=list(heading_path),
        )

    @classmethod
    def _grid(cls, rows_raw: list[dict], num_cols: int) -> list[list[str]]:
        """Every row, each padded to the table's column count.

        Args:
            rows_raw: The rows as the engine returned them.
            num_cols: How many columns the grid has.

        Returns:
            Every row padded to the table's column count.
        """
        return [cls._row(row, num_cols) for row in rows_raw]

    @classmethod
    def _row(cls, row: dict, num_cols: int) -> list[str]:
        """One row, filled by each cell's 1-indexed column number.

        Args:
            row: One row's cells.
            num_cols: How many columns the grid has.

        Returns:
            One row of cell strings.
        """
        cells: list[dict] = row.get("cells", [])
        data: list[str] = [""] * max(num_cols, len(cells))
        for cell in cells:
            data[cell.get("column number", 1) - 1] = cls._cell_text(cell)
        return data

    @staticmethod
    def _split(grid: list[list[str]]) -> tuple[list[str], list[list[str]]]:
        """The first row becomes headers only when data rows follow it.

        Args:
            grid: The table as a row-major grid.

        Returns:
            The header row and the data rows.
        """
        if len(grid) > 1:
            return grid[0], grid[1:]
        return [], grid

    @staticmethod
    def _cell_text(cell: dict) -> str:
        """A cell's text, concatenated from its nested kids.

        Args:
            cell: One cell.

        Returns:
            The cell's text, joined from its kids.
        """
        parts: list[str] = [kid.get("content", "").strip() for kid in cell.get("kids", [])]
        return " ".join(part for part in parts if part)
