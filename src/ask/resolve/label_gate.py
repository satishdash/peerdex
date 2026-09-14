"""Gate: a figure with no row label is not evidence."""

from ask.reading import Reading


class LabelGate:
    """Refuses a reading that names no row.

    Asking a model whether it was right returns yes; asking which row it read returns
    something testable. With no row named, there is nothing to test.
    """

    @staticmethod
    def check(reading: Reading) -> str:
        """Whether this reading names the row its value sits on.

        Args:
            reading: The figure and the evidence for it.

        Returns:
            The refusal reason, empty when the reading names a row.
        """
        if reading.label.strip():
            return ""
        return "no row label"
