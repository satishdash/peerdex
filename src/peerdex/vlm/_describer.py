"""OpenAI Vision describer.

One async method: describe(refs, doc_id) → list[dict|None].
Each entry mirrors the JSON schema enforced by the ingest prompt:
  {has_quant_data, title, description, values:[{label,value,unit}]}
or None if the call permanently failed (also written to DLQ).

Resilience: vlm_decorator (Bulkhead + Retry + Timeout + CircuitBreaker
+ Fallback). RPM/TPM token-buckets shared with the embedder.
Cache: per-image (sha256 + model + prompt_version) → skips API entirely
on hit. This makes re-running ingest safe and free.
"""

import asyncio
import base64
import json
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from openai import AsyncOpenAI

from peerdex.shared.logging import get_logger
from peerdex.shared.prompts import PROMPTS
from peerdex.shared.resilience import (
    openai_rpm_limiter,
    openai_tpm_limiter,
    vlm_decorator,
)
from peerdex.shared.settings import get_settings
from peerdex.vlm import _cache

log = get_logger("vlm.describer")


@dataclass
class PictureRef:
    page_no: int  # 1-based
    heading_path: list[str]  # ancestor section titles, root → leaf
    pil_image: Any  # PIL.Image (RGB)
    bbox_area_pct: float  # of page area, for logging only
    self_ref: str = ""  # docling self_ref, useful for debugging
    extra: dict = field(default_factory=dict)


def _png_bytes(pil_image: Any, max_dim: int) -> bytes:
    img = pil_image.convert("RGB") if hasattr(pil_image, "convert") else pil_image
    if hasattr(img, "thumbnail") and max_dim > 0:
        img.thumbnail((max_dim, max_dim))
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _parse_response(raw: str) -> dict[str, Any]:
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


class OpenAIPictureDescriber:
    def __init__(self, client: AsyncOpenAI, model: str | None = None) -> None:
        self._client = client
        self._model: str = model or get_settings().vlm.model

    async def _describe_one(self, ref: PictureRef, *, doc_id: str) -> dict[str, Any] | None:
        s = get_settings()
        png = _png_bytes(ref.pil_image, s.vlm.image_max_dim)
        key = _cache.cache_key(
            png,
            vlm_model=self._model,
            prompt_version=PROMPTS.prompt_version,
        )

        cached = _cache.get(key)
        if cached is not None:
            return cached

        # ---- inline call wrapped in vlm_decorator + RPM/TPM bucket ----
        def _on_failure(exc: BaseException, *_a, **_kw):
            _cache.dlq_put(
                doc_id,
                key,
                {
                    "page_no": ref.page_no,
                    "heading_path": ref.heading_path,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return None

        @vlm_decorator(on_failure=_on_failure)
        async def _call() -> dict[str, Any]:
            rpm, tpm = openai_rpm_limiter(), openai_tpm_limiter()
            # Image vision input is dominated by image tokens; this is a
            # rough guard for the shared TPM budget, not exact accounting.
            approx_tokens = 1500
            async with rpm:
                await tpm.acquire(approx_tokens)
                resp = await self._client.chat.completions.create(
                    model=self._model,
                    temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": PROMPTS.ingest_vlm_prompt},
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
                                        "url": "data:image/png;base64,"
                                        + base64.b64encode(png).decode()
                                    },
                                },
                            ],
                        },
                    ],
                )
            return _parse_response(resp.choices[0].message.content or "{}")

        result = await _call()
        if result is not None:
            _cache.put(key, result)
        return result

    async def describe(self, refs: list[PictureRef], *, doc_id: str) -> list[dict[str, Any] | None]:
        if not refs:
            return []
        log.info(f"[describer] {len(refs)} pictures, model={self._model}")
        return await asyncio.gather(*(self._describe_one(r, doc_id=doc_id) for r in refs))
