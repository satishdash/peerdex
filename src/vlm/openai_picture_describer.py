"""OpenAI Vision describer.

Each figure is sent to the vision model in a single JSON-mode call, and the reply
mirrors the schema the ingest prompt enforces: ``has_quant_data``, ``title``,
``description`` and ``values``. A permanently failed call yields None and a
dead-letter record.

Resilience is the shared decorator (bulkhead, retry, timeout, circuit breaker and
fallback) over the RPM and TPM buckets the embedder also draws on. A cache hit on
the image skips the API entirely, which is what makes re-running ingest free.
"""

import asyncio
import base64
import json
from collections.abc import Callable
from io import BytesIO
from typing import Any, ClassVar

from openai import AsyncOpenAI

from shared.document_prompts import DocumentPrompts
from shared.logging import Logging
from shared.resilience import Resilience
from shared.settings import get_settings
from vlm.dead_letter_queue import DeadLetterQueue
from vlm.description_cache import DescriptionCache
from vlm.picture_ref import PictureRef


class OpenAIPictureDescriber:
    """Describes figures through OpenAI Vision, one JSON-mode call per figure."""

    _LOG: ClassVar[Any] = Logging.get("vlm.openai_picture_describer")
    _APPROX_TOKENS: ClassVar[int] = 1500

    def __init__(self, client: AsyncOpenAI, model: str | None = None) -> None:
        """Bind to a client and the model that will describe the figures.

        Args:
            client: The OpenAI client.
            model: The vision model, or None to take it from settings.
        """
        self._client: AsyncOpenAI = client
        self._model: str = model or get_settings().vlm.model

    async def describe(self, refs: list[PictureRef], *, doc_id: str) -> list[dict[str, Any] | None]:
        """Describe every figure, concurrently.

        Args:
            refs: The figures to describe.
            doc_id: The document they came from, for the dead-letter queue.

        Returns:
            One description per figure, in order, None where the call failed for good.
        """
        if not refs:
            return []
        self._LOG.info(f"[describer] {len(refs)} pictures, model={self._model}")
        return await asyncio.gather(*(self._one(r, doc_id=doc_id) for r in refs))

    async def _one(self, ref: PictureRef, *, doc_id: str) -> dict[str, Any] | None:
        """One figure described, served from cache when the image was seen before.

        Args:
            ref: The figure to describe.
            doc_id: The document it came from.

        Returns:
            The description, or None when the call failed for good.
        """
        png: bytes = self._png(ref.pil_image, get_settings().vlm.image_max_dim)
        key: str = DescriptionCache.key(
            png, vlm_model=self._model, prompt_version=DocumentPrompts.current().prompt_version
        )
        cached: dict[str, Any] | None = DescriptionCache.get(key)
        if cached is not None:
            return cached

        result: dict[str, Any] | None = await self._guarded(ref, png, doc_id=doc_id, key=key)
        if result is not None:
            DescriptionCache.put(key, result)
        return result

    async def _guarded(
        self, ref: PictureRef, png: bytes, *, doc_id: str, key: str
    ) -> dict[str, Any] | None:
        """The call, wrapped in the resilience decorator that records a permanent failure.

        Args:
            ref: The figure to describe.
            png: That figure rendered as PNG bytes.
            doc_id: The document it came from.
            key: The cache key, which also keys the dead-letter record.

        Returns:
            The description, or None when the call failed for good.
        """

        @Resilience.vlm(on_failure=self._on_failure(ref, doc_id, key))
        async def call() -> dict[str, Any]:
            return await self._request(ref, png)

        return await call()

    async def _request(self, ref: PictureRef, png: bytes) -> dict[str, Any]:
        """One vision call, under the shared request and token buckets.

        Image input is dominated by image tokens, so the token charge is a rough
        guard on the shared budget rather than exact accounting.

        Args:
            ref: The figure to describe.
            png: That figure rendered as PNG bytes.

        Returns:
            The parsed description.
        """
        rpm, tpm = Resilience.rpm_limiter(), Resilience.tpm_limiter()
        async with rpm:
            await tpm.acquire(self._APPROX_TOKENS)
            resp = await self._client.chat.completions.create(
                model=self._model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": DocumentPrompts.current().ingest_vlm_prompt},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Figure on page {ref.page_no}, "
                                f"section: {' > '.join(ref.heading_path) or 'root'}.",
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/png;base64," + base64.b64encode(png).decode()
                                },
                            },
                        ],
                    },
                ],
            )
        return self._parsed(resp.choices[0].message.content or "{}")

    @staticmethod
    def _on_failure(ref: PictureRef, doc_id: str, key: str) -> Callable[..., None]:
        """The fallback the decorator runs once a figure has permanently failed.

        Args:
            ref: The figure that failed.
            doc_id: The document it came from.
            key: The cache key, which also keys the dead-letter record.

        Returns:
            A callable that records the failure and yields None.
        """

        def on_failure(exc: BaseException, *_a: Any, **_kw: Any) -> None:
            DeadLetterQueue.put(
                doc_id,
                key,
                {
                    "page_no": ref.page_no,
                    "heading_path": ref.heading_path,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return None

        return on_failure

    @staticmethod
    def _png(pil_image: Any, max_dim: int) -> bytes:
        """One figure as PNG bytes, shrunk to the configured longest side.

        Args:
            pil_image: The cut-out figure.
            max_dim: Longest side in pixels, or 0 to leave it alone.

        Returns:
            The encoded image.
        """
        img = pil_image.convert("RGB") if hasattr(pil_image, "convert") else pil_image
        if hasattr(img, "thumbnail") and max_dim > 0:
            img.thumbnail((max_dim, max_dim))
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    @staticmethod
    def _parsed(raw: str) -> dict[str, Any]:
        """The model's reply, coerced to the shape the prompt asks for.

        Args:
            raw: The raw JSON body.

        Returns:
            The description, with every field present and trimmed.
        """
        data = json.loads(raw or "{}")
        return {
            "has_quant_data": bool(data.get("has_quant_data", False)),
            "title": str(data.get("title") or "").strip(),
            "description": str(data.get("description") or "").strip(),
            "values": [
                {
                    "label": str(v.get("label") or "").strip(),
                    "value": str(v.get("value") or "").strip(),
                    "unit": str(v.get("unit") or "").strip(),
                }
                for v in (data.get("values") or [])
                if isinstance(v, dict)
            ],
        }
