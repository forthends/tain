# P8 — MCP Tool Integration

**Target:** v0.5.0
**Source:** [design doc supplement, section 3](../design/v0-4-2-design.md#mcp-工具集成)

## Current State

Tain agents can only use tools registered in their own `ToolRegistry`. No mechanism exists to dynamically discover and use external tools.

## Reference (Mini-Agent)

- `tools/mcp_loader.py` reads `mcp.json` config
- Connects to MCP servers via stdio / SSE / HTTP transports
- Wraps remote tools as local `MCPTool` instances
- Unified invocation through `tool.execute()`

## Implementation

### New file: `tain_agent/tools/mcp_loader.py`

```
- load_mcp_config(config_path) → list of server definitions
- MCPTool: Tool subclass that proxies execute() to remote MCP server
- Transport backends: StdioTransport, SSETransport, HTTPTransport
- Connection pool: reuse connections across tool calls
```

### Config file: `agent_workspace/<name>/mcp.json`

```json
{
  "mcpServers": {
    "web-search": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-server-brave-search"],
      "env": {"BRAVE_API_KEY": "${BRAVE_API_KEY}"}
    }
  }
}
```

### Modified: `config.yaml`

```yaml
tools:
  mcp_config: "mcp.json"     # path relative to agent workspace
  mcp_enabled: false          # opt-in per agent
```

## Verification

- Configure a local MCP server (e.g., filesystem), confirm tools appear in agent's tool list
- Agent calls MCP tool via chat, result flows back correctly
- Server disconnect/reconnect handled gracefully
- MCP config invalid → clear error, agent continues with local tools only
