"""Async OpenAI chat completion with transparent disk cache.

Cache key = sha256(model + temperature + seed + json(messages)).
Stored under the ``llm_cache`` namespace in the shared fsspec cache.

Usage::

    from peerdex.shared.llm import cached_completion

    rsp = await cached_completion(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello"}],
        temperature=0.0,
    )
    text = rsp.choices[0].message.content
"""

import json
from typing import Any

from openai.types.chat import ChatCompletion

from peerdex.shared.cache import get_json, hash_key, put_json
from peerdex.shared.clients import openai_async
from peerdex.shared.logging import get_logger

log = get_logger("llm.cache")

_NS = "llm_cache"


def _cache_key(
    model: str,
    messages: list[dict[str, Any]],
    temperature: float,
    seed: int | None,
    **_extra: Any,
) -> str:
    return hash_key(
        model,
        json.dumps(messages, sort_keys=True, ensure_ascii=False),
        str(temperature),
        str(seed or 0),
    )


async def cached_completion(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.0,
    seed: int | None = None,
    response_format: dict[str, str] | None = None,
    bypass_cache: bool = False,
) -> ChatCompletion:
    """Async chat completion with best-effort disk cache.

    On cache hit, returns a ``ChatCompletion`` parsed from the stored JSON —
    identical to what the API returns.  On miss, calls OpenAI and stores the
    response before returning.
    """
    key = _cache_key(model, messages, temperature, seed)

    if not bypass_cache:
        hit = get_json(_NS, key)
        if hit is not None:
            log.debug(f"[llm] cache hit {key[:12]}")
            return ChatCompletion.model_validate(hit)

    kwargs: dict[str, Any] = dict(
        model=model,
        messages=messages,
        temperature=temperature,
    )
    if seed is not None:
        kwargs["seed"] = seed
    if response_format is not None:
        kwargs["response_format"] = response_format

    client = openai_async()
    rsp = await client.chat.completions.create(**kwargs)

    try:
        put_json(_NS, key, rsp.model_dump())
        log.debug(f"[llm] cache store {key[:12]}")
    except Exception as exc:
        log.warning(f"[llm] cache write failed {key[:12]}: {exc}")

    return rsp
