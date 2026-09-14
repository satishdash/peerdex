"""Resilience policies built on pyresilience and aiolimiter.

Cheap LLM calls get retry and timeout only: a transient hiccup must not freeze
user-facing latency behind a circuit breaker. Vision calls in ingestion get the
full set, and their fallback returns None so the run continues with the other
images; the per-image cache and the dead-letter queue make it resumable.

The request and token limiters are one shared budget across every OpenAI caller.
"""

from collections.abc import Callable
from functools import lru_cache
from typing import Any, ClassVar

from aiolimiter import AsyncLimiter
from pyresilience import (
    BulkheadConfig,
    CircuitBreakerConfig,
    FallbackConfig,
    RetryConfig,
    TimeoutConfig,
    resilient,
)

from shared.settings import get_settings


class Resilience:
    """The retry, timeout, bulkhead and rate-limit policies every OpenAI caller shares."""

    _MINUTE: ClassVar[int] = 60
    _BULKHEAD_WAIT: ClassVar[float] = 60.0
    _BREAKER_THRESHOLD: ClassVar[int] = 10
    _BREAKER_RECOVERY: ClassVar[float] = 30.0

    @staticmethod
    @lru_cache(maxsize=1)
    def rpm_limiter() -> AsyncLimiter:
        """The shared requests-per-minute budget.

        Returns:
            The limiter.
        """
        return AsyncLimiter(max_rate=get_settings().resilience.openai_rpm, time_period=60)

    @staticmethod
    @lru_cache(maxsize=1)
    def tpm_limiter() -> AsyncLimiter:
        """The shared tokens-per-minute budget.

        Returns:
            The limiter.
        """
        return AsyncLimiter(max_rate=get_settings().resilience.openai_tpm, time_period=60)

    @staticmethod
    def light() -> Any:
        """Retry and timeout for cheap LLM calls. The caller supplies its own fallback.

        Returns:
            The decorator.
        """
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

    @classmethod
    def vlm(cls, *, on_failure: Callable[[BaseException], object]) -> Any:
        """Bulkhead, retry, timeout, circuit breaker and fallback for vision calls.

        Args:
            on_failure: Returns the fallback value once a call has failed for good.

        Returns:
            The decorator.
        """
        s = get_settings()
        return resilient(
            bulkhead=BulkheadConfig(max_concurrent=s.vlm.concurrency, max_wait=cls._BULKHEAD_WAIT),
            retry=RetryConfig(
                max_attempts=s.resilience.retry_attempts,
                delay=1.0,
                backoff_factor=2.0,
                max_delay=20.0,
                jitter=True,
            ),
            timeout=TimeoutConfig(seconds=s.resilience.timeout_seconds),
            circuit_breaker=CircuitBreakerConfig(
                failure_threshold=cls._BREAKER_THRESHOLD,
                recovery_timeout=cls._BREAKER_RECOVERY,
            ),
            fallback=FallbackConfig(handler=on_failure),
        )
