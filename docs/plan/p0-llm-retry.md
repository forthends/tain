# P0 — LLM Retry Mechanism

**Target:** v0.4.3
**Source:** [design doc, gap #1](../design/v0-4-2-design.md#1-llm-重试机制--tain-缺失)

## Current State

`tain_agent/core/llm.py` and `webui/dialogue.py` have no retry logic. Network issues, rate limits, or transient API errors cause immediate failure.

## Reference (Mini-Agent)

- `retry.py` — `async_retry` decorator with exponential backoff
- `RetryConfig`: `enabled`, `max_retries`, `initial_delay`, `max_delay`, `exponential_base`
- `RetryExhaustedError` carries `last_exception` and `attempts` for debugging
- `on_retry` callback notifies upper layers

## Implementation

### New file: `tain_agent/core/retry.py`

```
class RetryConfig:
    enabled: bool = True
    max_retries: int = 3
    initial_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    retryable_exceptions: tuple = (ConnectionError, TimeoutError, ...)

class RetryExhaustedError(Exception): ...

async def async_retry(config, on_retry=None):
    # delay = min(initial_delay * (base ^ attempt), max_delay)
    # + jitter ±10%
    # wraps async function, retries on retryable_exceptions
```

### Modified files

- `tain_agent/core/llm.py` — `AnthropicBackend.create_message()` and `OpenAICompatibleBackend.create_message()` wrap with retry
- `webui/dialogue.py` — `process_chat_message()` uses retry-wrapped backend calls
- `config.yaml` — add `llm.retry` section

### Config changes (`config.yaml`)

```yaml
llm:
  retry:
    enabled: true
    max_retries: 3
    initial_delay: 1.0
    max_delay: 30.0
    exponential_base: 2.0
```

## Verification

- Simulate network timeout via bad base_url, confirm retries + exhaustion error
- Simulate 429 rate limit, confirm backoff timing
- Normal call path unchanged (no retry overhead on success)
- Config `enabled: false` skips retry entirely

## Risks

- Retrying non-idempotent calls (e.g., partial writes due to timeout) may cause duplicates. Mitigation: limit retryable exceptions to network-layer only, exclude 4xx errors.
