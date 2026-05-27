# P10 — ACP Protocol Support

**Target:** v0.5.0
**Source:** [design doc supplement, section 4](../design/v0-4-2-design.md#四acp-协议agent-作为被嵌入的标准接口)

## Current State

Tain has `sub_agent.py` for inter-agent communication, but no standardized external protocol. Tain agents cannot be embedded in external editors/tools.

## Reference (Mini-Agent)

- `acp/server.py` wraps agent as ACP server over stdio
- Flow: `initialize → newSession → prompt → cancel`
- Streaming responses with thinking/content/tool_calls
- Compatible with Zed editor and other ACP clients

## Implementation

### New file: `tain_agent/acp/server.py`

```
ACP Server (stdio transport):
  - initialize(protocol_version, capabilities) → server_info
  - newSession(workspace_path) → session_id
  - prompt(session_id, text) → streaming events
  - cancel(session_id) → ack
  - closeSession(session_id) → ack
```

### Protocol messages (JSON-RPC over stdio)

```json
{"jsonrpc": "2.0", "method": "prompt", "params": {"session_id": "...", "text": "..."}, "id": 1}
```

### Integration

- Agent lifecycle: session creation → workspace init → agent start
- Reuse `process_chat_message()` SSE generator, adapt to ACP event format
- Cancel support reuses P3's `cancel_event` mechanism

## Verification

- Start ACP server via `python -m tain_agent.acp`
- Send initialize → newSession → prompt sequence
- Confirm streaming response events
- Cancel mid-response, confirm cleanup
- Test with ACP-compatible client (Zed editor or reference client)
