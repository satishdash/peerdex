"""A vision-model description rendered as the text a figure chunk carries."""


class FigureRenderer:
    """Renders a vision-model description as the text a figure chunk carries."""

    @classmethod
    def text(cls, page_no: int, heading_path: list[str], result: dict) -> str:
        """One described figure as a chunk body.

        Args:
            page_no: The page the figure sits on.
            heading_path: The ancestor headings, outermost first.
            result: The description returned by the vision model.

        Returns:
            The figure text, carrying its page, heading path, title, description and values.
        """
        head: str = " > ".join(heading_path) or "root"
        title: str = result.get("title") or "Figure"
        desc: str = result.get("description") or ""
        val_line: str = cls._values_line(result.get("values") or [])
        return f"[Figure p.{page_no} — {head}] {title}\n{desc}{val_line}".strip()

    @classmethod
    def _values_line(cls, values: list[dict]) -> str:
        """The figures read off the chart, as one line a keyword search can hit.

        Args:
            values: The label, value and unit triples the model read off.

        Returns:
            The line, empty when no value carries a label or a number.
        """
        parts: list[str] = [rendered for v in values if (rendered := cls._value(v))]
        if not parts:
            return ""
        return "\nValues: " + "; ".join(parts)

    @staticmethod
    def _value(v: dict) -> str:
        """One label, value and unit as text.

        Args:
            v: One value the model read off the figure.

        Returns:
            The rendered value, empty when it has neither a label nor a number.
        """
        label: str = v.get("label", "")
        value: str = v.get("value", "")
        if not (label or value):
            return ""
        unit: str = v.get("unit", "")
        piece: str = f"{label} = {value}".strip(" =")
        return f"{piece} {unit}" if unit else piece
