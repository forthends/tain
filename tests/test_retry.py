"""Tests for tain_agent.core.retry"""

import pytest
from tain_agent.core.retry import (
    RetryConfig, RetryExhaustedError, retry_call, retry_stream,
    _is_retryable, _calculate_delay,
)


class TestRetryConfig:
    def test_defaults(self):
        cfg = RetryConfig()
        assert cfg.enabled is True
        assert cfg.max_retries == 3
        assert cfg.initial_delay == 1.0
        assert cfg.max_delay == 30.0
        assert cfg.exponential_base == 2.0

    def test_from_config(self):
        cfg = RetryConfig.from_config({
            "retry": {
                "enabled": False,
                "max_retries": 5,
                "initial_delay": 2.0,
                "max_delay": 60.0,
                "exponential_base": 3.0,
            }
        })
        assert cfg.enabled is False
        assert cfg.max_retries == 5
        assert cfg.initial_delay == 2.0

    def test_from_config_defaults(self):
        cfg = RetryConfig.from_config({})
        assert cfg.enabled is True


class TestIsRetryable:
    def test_connection_error(self):
        assert _is_retryable(ConnectionError("refused")) is True

    def test_timeout_error(self):
        assert _is_retryable(TimeoutError("timed out")) is True

    def test_value_error_not_retryable(self):
        assert _is_retryable(ValueError("bad value")) is False

    def test_http_429_rate_limit(self):
        class Fake429:
            status_code = 429
        assert _is_retryable(Fake429()) is True

    def test_http_500_internal(self):
        class Fake500:
            status_code = 500
        assert _is_retryable(Fake500()) is True

    def test_http_400_bad_request(self):
        class Fake400:
            status_code = 400
        assert _is_retryable(Fake400()) is False

    def test_http_401_unauthorized(self):
        class Fake401:
            status_code = 401
        assert _is_retryable(Fake401()) is False


class TestCalculateDelay:
    def test_first_attempt(self):
        cfg = RetryConfig(initial_delay=1.0, exponential_base=2.0, max_delay=30.0)
        delay = _calculate_delay(cfg, 0)
        assert 0.0 <= delay <= 1.1  # delay + jitter

    def test_third_attempt(self):
        cfg = RetryConfig(initial_delay=1.0, exponential_base=2.0, max_delay=30.0)
        delay = _calculate_delay(cfg, 2)
        # 1.0 * 2^2 = 4.0, ±10% jitter
        assert 3.6 <= delay <= 4.4

    def test_max_delay_cap(self):
        cfg = RetryConfig(initial_delay=10.0, exponential_base=3.0, max_delay=30.0)
        delay = _calculate_delay(cfg, 4)
        assert delay <= 30.0 + (30.0 * 0.1)  # capped at max_delay + jitter


class TestRetryCall:
    def test_success_first_attempt(self):
        cfg = RetryConfig()
        result = retry_call(cfg, lambda: 42)
        assert result == 42

    def test_retry_then_success(self):
        cfg = RetryConfig(initial_delay=0.01)
        called = [0]

        def flaky():
            called[0] += 1
            if called[0] < 3:
                raise ConnectionError("fail")
            return "ok"

        result = retry_call(cfg, flaky)
        assert result == "ok"
        assert called[0] == 3

    def test_exhausted_retries(self):
        cfg = RetryConfig(max_retries=2, initial_delay=0.01)

        def always_fails():
            raise ConnectionError("always down")

        with pytest.raises(RetryExhaustedError) as exc:
            retry_call(cfg, always_fails)
        assert exc.value.attempts == 3  # initial + 2 retries

    def test_non_retryable_passes_through(self):
        cfg = RetryConfig(max_retries=3, initial_delay=0.01)

        def bad_request():
            raise ValueError("invalid")

        with pytest.raises(ValueError):
            retry_call(cfg, bad_request)

    def test_disabled_retry(self):
        cfg = RetryConfig(enabled=False)
        called = [0]

        def flaky():
            called[0] += 1
            if called[0] < 3:
                raise ConnectionError("fail")
            return "ok"

        with pytest.raises(ConnectionError):
            retry_call(cfg, flaky)
        assert called[0] == 1  # no retry, failed immediately

    def test_on_retry_callback(self):
        cfg = RetryConfig(max_retries=2, initial_delay=0.01)
        callbacks = []

        def always_fails():
            raise ConnectionError("fail")

        try:
            retry_call(cfg, always_fails, on_retry=lambda e, a, d: callbacks.append(a))
        except RetryExhaustedError:
            pass
        assert callbacks == [1, 2]


class TestRetryStream:
    def test_success_first_attempt(self):
        cfg = RetryConfig()

        def stream():
            yield from [1, 2, 3]

        result = list(retry_stream(cfg, stream))
        assert result == [1, 2, 3]

    def test_retry_then_success(self):
        cfg = RetryConfig(initial_delay=0.01)
        attempts = [0]

        def flaky_stream():
            attempts[0] += 1
            if attempts[0] < 2:
                raise ConnectionError("stream fail")
            yield from [10, 20]

        result = list(retry_stream(cfg, flaky_stream))
        assert result == [10, 20]
        assert attempts[0] == 2

    def test_non_retryable_skips(self):
        cfg = RetryConfig(initial_delay=0.01)

        def bad_stream():
            raise ValueError("bad")

        with pytest.raises(ValueError):
            list(retry_stream(cfg, bad_stream))
