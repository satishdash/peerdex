"""The opendataloader engine's identity, stamped into every parse's provenance."""

from typing import ClassVar


class EngineIdentity:
    """The opendataloader engine's name and version.

    The projection stamps them into provenance and the extractor publishes them on the
    port, so they live here rather than in either, which would make the two import
    each other.
    """

    NAME: ClassVar[str] = "odl"
    VERSION: ClassVar[str] = "1.0"
