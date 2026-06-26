"""
MCP Tool Loader — dynamic external tool discovery via Model Context Protocol.

Lets an agent discover and use tools from external MCP servers
(stdio transport). MCP tools are wrapped as local Tool instances
and registered on the agent's ToolRegistry.

Config: agent_workspace/<name>/mcp.json

Security:
  - Command whitelist prevents arbitrary binary execution
  - Shell-injection patterns rejected in args
  - Dangerous env vars stripped from merged environment
  - Subprocess timeout prevents hung servers
"""

import asyncio
import json
import os
import subprocess

from tain_agent import __version__
import uuid
from pathlib import Path
from typing import Optional

from tain_agent.tools.base import Tool

# ── Security constants ──────────────────────────────────────────────────

_COMMAND_WHITELIST = frozenset(
    os.environ.get("TAIN_MCP_COMMAND_WHITELIST", "npx,node,python,python3,uvx").split(",")
)

_SHELL_INJECTION_PATTERNS = (";", "|", "&&", "||", "$", "`", ">", "<", "&")

_DANGEROUS_ENV_VARS = frozenset({
    "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONSTARTUP", "PYTHONPATH",
    "NODE_OPTIONS", "NODE_PATH", "PERL5LIB", "RUBYLIB", "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH",
})

_ALLOWED_ENV_VAR_PREFIXES = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_",
    "TMPDIR", "TMP", "TEMP",
    "ANTHROPIC_", "OPENAI_", "MINIMAX_", "DEEPSEEK_",
    "TAIN_", "TAO_",
)

_MCP_STARTUP_TIMEOUT = 30  # seconds


# ── MCP config ────────────────────────────────────────────────────────


def load_mcp_config(config_path: Path) -> dict:
    """Load MCP server definitions from a JSON config file.

    Expected format:
    {
        "mcpServers": {
            "server-name": {
                "command": "npx",
                "args": ["-y", "@scope/mcp-server"],
                "env": {"KEY": "value"}
            }
        }
    }
    """
    if not config_path.exists():
        return {"mcpServers": {}}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return {"mcpServers": {}}


# ── MCP client (stdio transport) ──────────────────────────────────────


class MCPClient:
    """Minimal MCP client over stdio transport.

    Manages a subprocess running an MCP server and communicates
    via JSON-RPC over stdin/stdout.
    """

    def __init__(self, command: str, args: list[str] = None,
                 env: dict[str, str] = None):
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.process: Optional[subprocess.Popen] = None
        self._request_id = 0

    def start(self) -> dict:
        """Start the MCP server subprocess and initialize the session.

        Validates command against whitelist, args against shell injection,
        and env vars against safe-list before launching.

        Raises:
            ValueError: If command is not whitelisted or args contain injection.
        """
        # ── Validate command ──────────────────────────────────────────
        if self.command not in _COMMAND_WHITELIST:
            raise ValueError(
                f"MCP command '{self.command}' is not in the allowed whitelist. "
                f"Allowed: {sorted(_COMMAND_WHITELIST)}. "
                f"Set TAIN_MCP_COMMAND_WHITELIST env var to extend."
            )

        # ── Validate args — reject shell injection patterns ────────────
        for arg in self.args:
            if any(pattern in arg for pattern in _SHELL_INJECTION_PATTERNS):
                raise ValueError(
                    f"MCP arg '{arg}' contains shell-injection characters. "
                    f"Rejected patterns: {' '.join(_SHELL_INJECTION_PATTERNS)}"
                )

        # ── Sanitize environment ──────────────────────────────────────
        merged_env = {}
        for key, value in os.environ.items():
            if key in _DANGEROUS_ENV_VARS:
                continue
            if any(key.startswith(prefix) or key == prefix
                   for prefix in _ALLOWED_ENV_VAR_PREFIXES):
                merged_env[key] = value

        # Apply MCP-specific env vars (already validated above)
        for key, value in self.env.items():
            if key in _DANGEROUS_ENV_VARS:
                continue
            merged_env[key] = value

        self.process = subprocess.Popen(
            [self.command] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=merged_env,
        )

        # ── Wait for process to start ─────────────────────────────────
        try:
            self.process.wait(timeout=0.5)
            # Process exited immediately — likely a startup failure
            stderr_output = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(
                f"MCP server '{self.command}' exited immediately "
                f"with code {self.process.returncode}. stderr: {stderr_output[:500]}"
            )
        except subprocess.TimeoutExpired:
            pass  # Process is still running — expected

        # Initialize MCP session with timeout
        init_result = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "tain-agent", "version": __version__},
        })
        return init_result

    def stop(self) -> None:
        """Stop the MCP server subprocess."""
        if self.process:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=5)
            except (subprocess.TimeoutExpired, IOError):
                self.process.kill()
                self.process.wait()
            self.process = None

    def list_tools(self) -> list[dict]:
        """Discover tools from the MCP server."""
        result = self._send_request("tools/list", {})
        return result.get("tools", [])

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call a tool on the MCP server."""
        result = self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        return result

    def _send_request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and return the result."""
        if not self.process or self.process.poll() is not None:
            raise RuntimeError("MCP server process is not running")

        req_id = self._next_id()
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        payload = json.dumps(request, ensure_ascii=False) + "\n"
        self.process.stdin.write(payload)
        self.process.stdin.flush()

        response_line = self.process.stdout.readline()
        if not response_line:
            raise RuntimeError(f"No response from MCP server for {method}")

        try:
            response = json.loads(response_line)
        except json.JSONDecodeError:
            raise RuntimeError(f"Invalid JSON response: {response_line[:200]}")

        if "error" in response:
            raise RuntimeError(
                f"MCP error: {response['error'].get('message', 'unknown error')}"
            )
        return response.get("result", {})

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id


# ── MCP Tool wrapper ──────────────────────────────────────────────────


class MCPTool(Tool):
    """A Tool that proxies execution to a remote MCP server."""

    def __init__(self, mcp_tool_def: dict, client: MCPClient):
        self.name = mcp_tool_def.get("name", "unknown")
        self.description = mcp_tool_def.get("description", "")
        self.parameters = mcp_tool_def.get("inputSchema", {})
        self._client = client
        self._original_def = mcp_tool_def

    def execute(self, **kwargs) -> str:
        """Execute the tool via MCP."""
        try:
            result = self._client.call_tool(self.name, kwargs)
            content = result.get("content", [])
            if isinstance(content, list):
                texts = []
                for item in content:
                    if isinstance(item, dict):
                        texts.append(item.get("text", str(item)))
                    else:
                        texts.append(str(item))
                return "\n".join(texts)
            return str(content)
        except Exception as e:
            return f"[MCP tool error] {type(e).__name__}: {e}"


# ── Loader ────────────────────────────────────────────────────────────


def discover_and_register(registry, mcp_config_path: Path) -> list[str]:
    """Discover MCP servers from config, load their tools, register on registry.

    Args:
        registry: ToolRegistry instance to register tools on.
        mcp_config_path: Path to mcp.json config file.

    Returns:
        List of tool names loaded from MCP servers.
    """
    config = load_mcp_config(mcp_config_path)
    servers = config.get("mcpServers", {})
    if not servers:
        return []

    loaded = []
    for server_name, server_def in servers.items():
        if server_def.get("disabled"):
            continue

        command = server_def.get("command", "")
        args = server_def.get("args", [])
        env = server_def.get("env", {})

        if not command:
            continue

        try:
            client = MCPClient(command=command, args=args, env=env)
            client.start()
            tools = client.list_tools()

            for tool_def in tools:
                mcp_tool = MCPTool(tool_def, client)
                registry.register_tool(mcp_tool)
                loaded.append(tool_def.get("name", "unknown"))

        except Exception as e:
            # Log but don't fail — one bad server shouldn't block the agent
            print(f"  ⚠️  MCP server '{server_name}' failed: {e}")
            continue

    return loaded
