# P2 — Structured LLM Logging

**Target:** v0.4.4
**Source:** [design doc, gap #3](../design/v0-4-2-design.md#3-结构化-llm-日志--tain-缺失)

## Current State

`DecisionLog` records agent decisions (context/options/reasoning/outcome) but not raw LLM request/response. Debugging requires external packet capture or print statements.

## Reference (Mini-Agent)

- `AgentLogger` — per-run JSONL log files
- Events: `log_request`, `log_response`, `log_tool_result`
- Stored in `~/.mini-agent/log/` with timestamped filenames
- `/log` CLI command for viewing

## Implementation

### New file: `tain_agent/core/llm_logger.py`

```python
class LLMLogger:
    def __init__(self, log_dir: Path):
        self.log_path = log_dir / f"llm_{timestamp}.jsonl"

    def log_request(self, provider, model, messages_count, estimated_tokens, tools):
        # {"type": "request", "timestamp": ..., "provider": ..., ...}

    def log_response(self, content, thinking, tool_calls, finish_reason, token_usage, latency_ms):
        # {"type": "response", "timestamp": ..., ...}

    def log_tool_result(self, tool_name, arguments, success, result_summary, latency_ms):
        # {"type": "tool_result", "timestamp": ..., ...}
```

### Modified files

- `tain_agent/core/llm.py` — backends accept optional `LLMLogger`, call log_request/log_response
- `tain_agent/core/agent.py` — pass logger to backend, log tool execution results
- `webui/dialogue.py` — pass logger through to agent/backend
- Web UI: new "LLM Calls" tab in agent detail (or add to existing "Live" tab)

### Storage

`agent_workspace/<agent_name>/logs/llm_calls.jsonl`

## Verification

- Run agent with chat, confirm JSONL file created with request/response/tool events
- Check latency_ms and token_usage fields populated
- Long content is truncated (no giant JSONL lines)
- Web UI tab renders log entries
