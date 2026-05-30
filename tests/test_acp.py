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
        from tain_agent.acp.server import PROJECT_ROOT
        server = ACPServer()
        valid_ws = str(PROJECT_ROOT / "agent_workspace" / "test_acp_ws")
        result = await server._handle_new_session(
            {"workspace_path": valid_ws}, 1
        )
        assert result["result"]["workspace_path"] == valid_ws
        assert "acp_" in result["result"]["session_id"]

    @pytest.mark.asyncio
    async def test_new_session_rejects_path_traversal(self):
        server = ACPServer()
        result = await server._handle_new_session(
            {"workspace_path": "/tmp/escape_attempt"}, 1
        )
        assert "error" in result
        assert result["error"]["code"] == -32001


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


class TestACPPrompt:
    @pytest.mark.asyncio
    async def test_prompt_uses_chat_engine(self, monkeypatch):
        """Verify _handle_prompt uses ChatEngine (not webui.dialogue)."""
        from tain_agent.core.chat import ChatTurn
        from tain_agent.core.llm import ToolCall

        fake_turn = ChatTurn(
            text="Hello from ChatEngine",
            tool_calls=[ToolCall(id="tc_1", name="read_file", input={"path": "x"})],
            tool_results=[{"tool_use_id": "tc_1", "content": "contents"}],
        )

        # Capture events written to stdout
        events_sent: list[dict] = []
        orig_send = ACPServer._send_event

        def capture_send(self, session_id, event):
            event["session_id"] = session_id
            events_sent.append(dict(event))

        monkeypatch.setattr(ACPServer, "_send_event", capture_send)

        async def fake_run_turn(self, messages, cancel_event):
            return fake_turn

        monkeypatch.setattr("tain_agent.core.chat.ChatEngine.run_turn", fake_run_turn)

        server = ACPServer()
        session_result = await server._handle_new_session({}, 1)
        sid = session_result["result"]["session_id"]

        await server._handle_prompt({"session_id": sid, "text": "hi"}, 99)

        text_events = [e for e in events_sent if e["type"] == "text"]
        tool_events = [e for e in events_sent if e["type"] == "tool_call"]

        assert len(text_events) >= 1
        assert "Hello from ChatEngine" in text_events[0]["text"]
        assert len(tool_events) >= 1
        assert tool_events[0]["name"] == "read_file"

    @pytest.mark.asyncio
    async def test_prompt_unknown_session(self):
        server = ACPServer()
        result = await server._handle_prompt({"session_id": "no_such_session", "text": "hi"}, 1)
        assert "error" in result
        assert result["error"]["code"] == -32000


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
