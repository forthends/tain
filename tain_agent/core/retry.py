"""
Exponential backoff retry for LLM API calls.

Handles transient failures (network issues, rate limits, 5xx) while
failing fast on permanent errors (auth, bad request).
"""

import random
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class RetryConfig:
    enabled: bool = True
    max_retries: int = 3
    initial_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0

    @classmethod
    def from_config(cls, cfg: dict) -> "RetryConfig":
        retry_cfg = cfg.get("retry", {})
        return cls(
            enabled=retry_cfg.get("enabled", True),
            max_retries=retry_cfg.get("max_retries", 3),
            initial_delay=retry_cfg.get("initial_delay", 1.0),
            max_delay=retry_cfg.get("max_delay", 30.0),
            exponential_base=retry_cfg.get("exponential_base", 2.0),
        )


class RetryExhaustedError(Exception):
    """Raised when all retry attempts are exhausted."""

    def __init__(self, last_exception: Exception, attempts: int):
        self.last_exception = last_exception
        self.attempts = attempts
        super().__init__(
            f"Retry exhausted after {attempts} attempts. "
            f"Last error: {type(last_exception).__name__}: {last_exception}"
        )


# Exceptions that should trigger a retry (by class name, so we don't
# hard-depend on specific SDKs being installed).
_RETRYABLE_EXCEPTION_NAMES = frozenset({
    # Generic
    "ConnectionError", "TimeoutError", "Timeout", "ConnectTimeout",
    "ReadTimeout", "ConnectionResetError",
    # Anthropic SDK
    "APIConnectionError", "RateLimitError", "APITimeoutError",
    "InternalServerError", "APIStatusError",
    # OpenAI SDK
    "APITimeoutError", "APIConnectionError", "RateLimitError",
    "InternalServerError",
})

_NON_RETRYABLE_EXCEPTION_NAMES = frozenset({
    "BadRequestError", "AuthenticationError", "PermissionDeniedError",
    "NotFoundError",
})


def _is_retryable(exception: Exception) -> bool:
    name = type(exception).__name__
    if name in _NON_RETRYABLE_EXCEPTION_NAMES:
        return False
    if name in _RETRYABLE_EXCEPTION_NAMES:
        return True
    # Check HTTP status codes on API errors
    status = getattr(exception, 'status_code', None) or getattr(exception, 'http_status', None)
    if status is not None:
        if 400 <= status < 500 and status != 429:
            return False
        return status >= 500 or status == 429
    # Default: not retryable (don't retry unknown errors)
    return False


def _calculate_delay(config: RetryConfig, attempt: int) -> float:
    delay = config.initial_delay * (config.exponential_base ** attempt)
    delay = min(delay, config.max_delay)
    jitter = delay * 0.1 * random.random()
    return delay + jitter


def retry_call(
    config: RetryConfig,
    func: Callable,
    *args,
    on_retry: Optional[Callable[[Exception, int, float], None]] = None,
    **kwargs,
):
    """Call func(*args, **kwargs) with exponential backoff retry.

    Args:
        config: RetryConfig with enabled/max_retries/backoff parameters.
        func: The callable to retry.
        on_retry: Optional callback(exception, attempt_number, delay_seconds)
                  called before each retry sleep.

    Returns:
        The return value of func.

    Raises:
        RetryExhaustedError: when all retries are exhausted.
        The original exception: for non-retryable errors.
    """
    if not config.enabled:
        return func(*args, **kwargs)

    last_exception = None
    for attempt in range(config.max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exception = exc
            if not _is_retryable(exc):
                raise
            if attempt >= config.max_retries:
                raise RetryExhaustedError(last_exception, attempt + 1) from last_exception
            delay = _calculate_delay(config, attempt)
            if on_retry:
                on_retry(exc, attempt + 1, delay)
            time.sleep(delay)

    raise RetryExhaustedError(last_exception, config.max_retries + 1)


def retry_stream(
    config: RetryConfig,
    stream_factory: Callable,
    on_retry: Optional[Callable[[Exception, int, float], None]] = None,
):
    """Retry-aware wrapper for stream generators.

    Retries the stream creation (the factory call). Once the stream starts
    yielding events, those are passed through directly — mid-stream failures
    are not retried since partial state makes restart complex.

    Args:
        config: RetryConfig.
        stream_factory: A zero-arg callable that returns an iterator/generator.
        on_retry: Optional callback before each retry sleep.

    Yields:
        Items from the stream.

    Raises:
        RetryExhaustedError: when stream creation fails after all retries.
    """
    if not config.enabled:
        yield from stream_factory()
        return

    last_exception = None
    for attempt in range(config.max_retries + 1):
        try:
            stream = stream_factory()
            yield from stream
            return  # stream completed successfully
        except Exception as exc:
            last_exception = exc
            if not _is_retryable(exc):
                raise
            if attempt >= config.max_retries:
                raise RetryExhaustedError(last_exception, attempt + 1) from last_exception
            delay = _calculate_delay(config, attempt)
            if on_retry:
                on_retry(exc, attempt + 1, delay)
            time.sleep(delay)

    raise RetryExhaustedError(last_exception, config.max_retries + 1)


def llm_retry_call(
    config: RetryConfig,
    func: Callable,
    *args,
    on_rate_limit: Optional[Callable[[], bool]] = None,
    on_trim: Optional[Callable[[], None]] = None,
    **kwargs,
):
    """LLM-specific retry with rate-limit awareness and conversation-trimming fallback.

    Differs from retry_call: on rate limit (429), calls on_rate_limit() which
    should check _rate_limit_exit_code. On other retryable failures, calls
    on_trim() to trim conversation before the last retry attempt.

    Returns:
        The return value of func on success, None on rate-limit exit.
    """
    if not config.enabled:
        return func(*args, **kwargs)

    last_exception = None
    for attempt in range(config.max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exception = exc
            err_str = str(exc)

            if "429" in err_str or "rate_limit" in err_str.lower():
                if on_rate_limit:
                    should_exit = on_rate_limit(err_str)
                    if should_exit:
                        return None
                delay = _calculate_delay(config, attempt) * 2
                time.sleep(delay)
                continue

            if not _is_retryable(exc):
                raise

            if attempt >= config.max_retries:
                raise RetryExhaustedError(last_exception, attempt + 1) from last_exception

            if attempt == config.max_retries - 1 and on_trim:
                on_trim()

            delay = _calculate_delay(config, attempt)
            time.sleep(delay)

    return None
