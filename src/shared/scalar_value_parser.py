"""One CLI value typed as bool, int or text."""

from shared.metadata import Scalar
from shared.value_parser import ValueParser


class ScalarValueParser(ValueParser[Scalar]):
    """``true``/``false`` become bool, bare digits become int, anything else stays text."""

    def parse(self, raw: str) -> Scalar:
        """The typed value for one piece of text.

        Args:
            raw: The text right of ``=``.

        Returns:
            The typed value.
        """
        if raw.lower() in ("true", "false"):
            return raw.lower() == "true"
        return int(raw) if raw.isdigit() else raw
