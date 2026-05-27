"""Tests for tain_agent.acp.server"""

import json
import pytest
from tain_agent.acp.server import ACPServer, _now_iso


class TestACPServerInit:
    def test_default_config_path(self):
        server = ACPServer()
        assert "config.yaml" in server.config_path
        assert server.sessions == {}
        assert server._running is False

    def test_explicit_config_path(self):
        server = ACPServer(config_path="/tmp/my_config.yaml")
        assert server.config_path == "/tmp/my_config.yaml"


class TestACPInitialize:
    @pytest.mark.asyncio
    async def test_initialize_response(self):
        server = ACPServer()
        result = await server._handle_initialize({}, 1)
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == 1
        assert result["result"]["protocolVersion"] == "2025-01-01"
        assert result["result"]["serverInfo"]["name"] == "tain-agent-acp"
        assert result["result"]["capabilities"]["streaming"] is True
        assert result["result"]["capabilities"]["cancellation"] is True


class TestACPNewSession:
    @pytest.mark.asyncio
    async def test_new_session(self):
        server = ACPServer()
        result = await server._handle_new_session({}, 1)
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == 1
        session_id = result["result"]["session_id"]
        assert session_id.startswith("acp_")
        assert session_id in server.sessions

    @pytest.mark.asyncio
    async def test_new_session_with_workspace(self):
        server = ACPServer()
        result = await server._handle_new_session(
            {"workspace_path": "/tmp/test_acp_ws"}, 1
        )
        assert result["result"]["workspace_path"] == "/tmp/test_acp_ws"
        assert "acp_" in result["result"]["session_id"]


class TestACPCancel:
    @pytest.mark.asyncio
    async def test_cancel_existing_session(self):
        server = ACPServer()
        session_result = await server._handle_new_session({}, 1)
        sid = session_result["result"]["session_id"]

        result = await server._handle_cancel({"session_id": sid}, 2)
        assert result["result"]["cancelled"] is True

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_session(self):
        server = ACPServer()
        result = await server._handle_cancel({"session_id": "nonexistent"}, 1)
        assert result["result"]["cancelled"] is False


class TestACPCloseSession:
    @pytest.mark.asyncio
    async def test_close_session(self):
        server = ACPServer()
        session_result = await server._handle_new_session({}, 1)
        sid = session_result["result"]["session_id"]

        result = await server._handle_close_session({"session_id": sid}, 2)
        assert result["result"]["closed"] is True
        assert sid not in server.sessions

    @pytest.mark.asyncio
    async def test_close_nonexistent(self):
        server = ACPServer()
        result = await server._handle_close_session(
            {"session_id": "nonexistent"}, 1
        )
        assert result["result"]["closed"] is False


class TestACPEventConversion:
    def test_text_delta_event(self):
        server = ACPServer()
        sse = {"text": "hello"}
        acp = server._convert_to_acp_event(sse)
        assert acp["type"] == "text_delta"
        assert acp["text"] == "hello"

    def test_tool_start_event(self):
        server = ACPServer()
        sse = {"tool_start": {"name": "read_file", "input_preview": "{}"}}
        acp = server._convert_to_acp_event(sse)
        assert acp["type"] == "tool_call"
        assert acp["tool"]["name"] == "read_file"

    def test_done_event(self):
        server = ACPServer()
        sse = {"done": True, "message_id": "msg_123"}
        acp = server._convert_to_acp_event(sse)
        assert acp["type"] == "done"
        assert acp["message_id"] == "msg_123"

    def test_thinking_event(self):
        server = ACPServer()
        sse = {"status": "thinking"}
        acp = server._convert_to_acp_event(sse)
        assert acp["type"] == "thinking"

    def test_cancelled_event(self):
        server = ACPServer()
        sse = {"cancelled": True}
        acp = server._convert_to_acp_event(sse)
        assert acp["type"] == "cancelled"


class TestACPMethodRouting:
    @pytest.mark.asyncio
    async def test_unknown_method(self):
        server = ACPServer()
        result = await server._handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "unknownMethod", "params": {},
        })
        assert result is not None
        assert "error" in result
        assert result["error"]["code"] == -32601


class TestNowIso:
    def test_format(self):
        ts = _now_iso()
        assert "T" in ts
        assert "+" in ts or "Z" in ts
