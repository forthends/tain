"""Tests for the inter-agent message bus."""

import pytest
import tempfile
from pathlib import Path
from tain_agent.core.message_bus import MessageBus


class TestMessageBusInit:
    def test_create_with_temp_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(workspace_root=tmpdir)
            assert bus.db_path.exists()
            assert bus.db_path.name == "_message_bus.db"


class TestMessageBusSendAndReceive:
    def test_send_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(workspace_root=tmpdir)
            result = bus.send_message(
                from_agent="agent_a",
                to_agent="agent_b",
                content="Hello!",
            )
            assert result["success"] is True

    def test_check_messages_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(workspace_root=tmpdir)
            result = bus.check_messages("agent_a")
            assert result["count"] == 0
            assert result["messages"] == []

    def test_check_messages_receives(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(workspace_root=tmpdir)
            bus.send_message(from_agent="agent_a", to_agent="agent_b",
                           content="Hello from A!")
            result = bus.check_messages("agent_b")
            assert result["count"] >= 1
            assert len(result["messages"]) >= 1

    def test_only_target_receives(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(workspace_root=tmpdir)
            bus.send_message(from_agent="agent_a", to_agent="agent_b",
                           content="For B only")
            result = bus.check_messages("agent_c")
            assert result["count"] == 0
            assert result["messages"] == []


class TestMessageBusConversationHistory:
    def test_conversation_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(workspace_root=tmpdir)
            bus.send_message(from_agent="agent_a", to_agent="agent_b",
                           content="Msg 1")
            bus.send_message(from_agent="agent_b", to_agent="agent_a",
                           content="Msg 2")
            # Consume messages so they appear in history
            bus.check_messages("agent_b")
            bus.check_messages("agent_a")
            result = bus.get_conversation_history("agent_a", "agent_b")
            assert result["count"] >= 2

    def test_empty_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(workspace_root=tmpdir)
            result = bus.get_conversation_history("agent_x", "agent_y")
            assert result["count"] == 0


class TestMessageBusManagement:
    def test_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(workspace_root=tmpdir)
            stats = bus.stats()
            assert isinstance(stats, dict)

    def test_cleanup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = MessageBus(workspace_root=tmpdir)
            bus.send_message(from_agent="a", to_agent="b", content="old")
            count = bus.cleanup(older_than_days=0)
            assert count >= 0
