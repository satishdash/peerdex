"""Resilience policies built on pyresilience + aiolimiter.

Two decorator factories:

  light_decorator()   → cheap LLM calls (expand, rerank, synth):
                        Retry + Timeout. No circuit breaker — a transient
                        OpenAI hiccup must not freeze user-facing latency.

  vlm_decorator(...)  → OpenAI Vision calls in ingestion:
                        Bulkhead + Retry + Timeout + CircuitBreaker +
                        Fallback. The fallback handler returns ``None`` so
                        the orchestrator can continue with other images
                        (the per-image cache + DLQ ensures resumability).

Plus token-bucket limiters for the shared OpenAI RPM/TPM budget.
"""

from functools import lru_cache
from typing import Callable

from aiolimiter import AsyncLimiter
from pyresilience import (
    BulkheadConfig,
    CircuitBreakerConfig,
    FallbackConfig,
    RetryConfig,
    TimeoutConfig,
    resilient,
)

from peerdex.shared.settings import get_settings


# ---------- shared OpenAI RPM/TPM limiters ----------

@lru_cache(maxsize=1)
def openai_rpm_limiter() -> AsyncLimiter:
    s = get_settings()
    return AsyncLimiter(max_rate=s.resilience.openai_rpm, time_period=60)


@lru_cache(maxsize=1)
def openai_tpm_limiter() -> AsyncLimiter:
    s = get_settings()
    return AsyncLimiter(max_rate=s.resilience.openai_tpm, time_period=60)


# ---------- decorator factories ----------

def light_decorator():
    """Retry + Timeout for cheap LLM calls. Caller supplies its own fallback."""
    s = get_settings()
    return resilient(
        retry=RetryConfig(
            max_attempts=s.resilience.retry_attempts,
            delay=0.5,
            backoff_factor=2.0,
            max_delay=8.0,
            jitter=True,
        ),
        timeout=TimeoutConfig(seconds=s.resilience.timeout_seconds),
    )


def vlm_decorator(*, on_failure: Callable[[BaseException], object]):
    """Heavy resilience for OpenAI Vision. ``on_failure`` returns the fallback value."""
    s = get_settings()
    return resilient(
        bulkhead=BulkheadConfig(max_concurrent=s.vlm.concurrency, max_wait=60.0),
        retry=RetryConfig(
            max_attempts=s.resilience.retry_attempts,
            delay=1.0,
            backoff_factor=2.0,
            max_delay=20.0,
            jitter=True,
        ),
        timeout=TimeoutConfig(seconds=s.resilience.timeout_seconds),
        circuit_breaker=CircuitBreakerConfig(
            failure_threshold=10, recovery_timeout=30.0,
        ),
        fallback=FallbackConfig(handler=on_failure),
    )
