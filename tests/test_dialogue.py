"""Tests for webui.dialogue cancel mechanism"""

import asyncio
import json
import pytest
from webui.dialogue import cancel_chat_message, _active_cancel_events, _cleanup_incomplete_messages


class TestCancelChatMessage:
    def test_cancel_existing_event(self):
        msg_id = "test_msg_123"
        event = asyncio.Event()
        _active_cancel_events[msg_id] = event
        try:
            result = cancel_chat_message(msg_id)
            assert result is True
            assert event.is_set()
        finally:
            _active_cancel_events.pop(msg_id, None)

    def test_cancel_nonexistent_event(self):
        result = cancel_chat_message("nonexistent_id")
        assert result is False

    def test_cancel_already_set_event(self):
        msg_id = "test_already_set"
        event = asyncio.Event()
        event.set()  # already cancelled
        _active_cancel_events[msg_id] = event
        try:
            result = cancel_chat_message(msg_id)
            assert result is False  # already set
        finally:
            _active_cancel_events.pop(msg_id, None)


class TestCleanupIncompleteMessages:
    def test_empty_list(self):
        msgs = []
        _cleanup_incomplete_messages(msgs)
        assert msgs == []

    def test_no_cleanup_needed(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        original_len = len(msgs)
        _cleanup_incomplete_messages(msgs)
        assert len(msgs) == original_len

    def test_removes_incomplete_tool_use(self):
        msgs = [
            {"role": "user", "content": "read a file"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Let me read that"},
                {"type": "tool_use", "id": "tool_1", "name": "read", "input": {}},
            ]},
            # No matching tool_result!
        ]
        _cleanup_incomplete_messages(msgs)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_preserves_complete_tool_sequence(self):
        msgs = [
            {"role": "user", "content": "read a file"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "tool_1", "name": "read", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tool_1", "content": "file contents"},
            ]},
        ]
        original_len = len(msgs)
        _cleanup_incomplete_messages(msgs)
        assert len(msgs) == original_len  # complete pair preserved

    def test_text_only_assistant_not_removed(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        _cleanup_incomplete_messages(msgs)
        assert len(msgs) == 2
