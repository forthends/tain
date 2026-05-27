# P1 — Token-Aware Context Management

**Target:** v0.4.3
**Source:** [design doc, gap #2](../design/v0-4-2-design.md#2-token-感知上下文管理--tain-使用固定窗口)

## Current State

`tain_agent/core/conversation.py` uses `keep_first_and_last(8)` — a fixed message-count window. Large tool results (file reads, web search) can exceed model context limits, causing API failures.

## Reference (Mini-Agent)

- `_estimate_tokens()` — tiktoken (`cl100k_base`) exact counting on full message history
- Dual trigger: local estimate OR API-reported `total_tokens` exceeding limit
- `_summarize_messages()` — preserves user messages + system prompt, compresses execution blocks
- `_skip_next_token_check` — prevents infinite summary loops
- Fallback: char-based estimate (2.5 chars/token) when tiktoken unavailable

## Implementation

### Modified: `tain_agent/core/conversation.py`

Add to `ConversationManager`:

- `estimate_tokens()` — tiktoken count with char fallback
- `token_limit` config (default 80000)
- `summarize()` — LLM-driven compression of execution blocks between user messages
- `_find_safe_boundary()` — existing logic, ensure tool_use/tool_result pairs stay intact
- Replace `keep_first_and_last(N)` with token-aware truncation

### Summarization strategy

```
For each user message:
  new_messages.append(user_message)          # preserve user intent
  execution_msgs = messages between this user and next
  if execution_msgs:
    summary = llm.summarize(execution_msgs)   # compress execution
    new_messages.append({"role": "assistant", "content": summary})
messages = [system_prompt] + new_messages
```

### Config changes (`config.yaml`)

```yaml
conversation:
  token_limit: 80000
  model_context_window: 131072  # M2.7 context size
```

### New dependency (optional)

`tiktoken` (~1MB). Fallback to `len(text) / 2.5` if not installed.

## Verification

- Feed 100k+ tokens of tool results, confirm summarization triggers
- Confirm user messages are never summarized away
- Confirm tool_use/tool_result pairs are never split
- tiktoken unavailable → char fallback still works
- API response `total_tokens` also triggers summarization

## Risks

- Summarization is irreversible information loss — use conservative `token_limit` (80k is ~60% of 131k context)
- Model-specific tokenizers differ (±5%) — use API `total_tokens` as secondary trigger
- Skip subsequent checks to avoid infinite summarization loops
