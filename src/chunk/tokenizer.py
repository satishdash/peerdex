"""Token counting, with the encoding the embedding model itself uses."""

import tiktoken

from shared.settings import get_settings


class Tokenizer:
    """Counts tokens with the encoding the embedding model itself uses."""

    @classmethod
    def encoding(cls) -> tiktoken.Encoding:
        """The tiktoken encoding named in settings.

        Returns:
            The encoding.
        """
        return tiktoken.get_encoding(get_settings().chunker.tokenizer)

    @classmethod
    def count(cls, text: str) -> int:
        """What text costs against a chunk's token budget.

        Args:
            text: The text to measure.

        Returns:
            The token count.
        """
        return len(cls.encoding().encode(text))
