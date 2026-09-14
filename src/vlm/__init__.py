"""VLM picture describer.

The extractor pre-filters pictures by bounding-box area and header/footer band, then
each surviving picture goes to OpenAI Vision in a single JSON-mode call. Results cache
per image; permanent failures go to a per-document dead-letter queue. The chunker turns
the descriptions into figure chunks.
"""

from vlm.blob_store import BlobStore
from vlm.dead_letter_queue import DeadLetterQueue
from vlm.description_cache import DescriptionCache
from vlm.openai_picture_describer import OpenAIPictureDescriber
from vlm.picture_ref import PictureRef

__all__ = [
    "BlobStore",
    "DeadLetterQueue",
    "DescriptionCache",
    "OpenAIPictureDescriber",
    "PictureRef",
]
