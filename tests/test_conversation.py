"""Tests for tain_agent.core.conversation"""

import pytest
from tain_agent.core.conversation import ConversationManager


class TestTokenEstimation:
    def test_empty_history(self):
        cm = ConversationManager()
        assert cm.estimate_tokens() > 0  # at least 1 token

    def test_with_messages(self):
        cm = ConversationManager()
        cm.append("user", "Hello, how are you?")
        cm.append("assistant", "I'm doing well, thank you!")
        est = cm.estimate_tokens()
        assert est > 0

    def test_with_tool_blocks(self):
        cm = ConversationManager()
        cm.append("user", "Read a file")
        cm.append("assistant", [
            {"type": "tool_use", "id": "1", "name": "read", "input": {"path": "/tmp/test"}},
        ])
        cm.append("user", [
            {"type": "tool_result", "tool_use_id": "1", "content": "file contents here"},
        ])
        est = cm.estimate_tokens()
        assert est > 0

    def test_large_history_estimation(self):
        cm = ConversationManager(token_limit=1000)
        for i in range(20):
            cm.append("user", f"Message number {i} " + "x" * 200)
            cm.append("assistant", "y" * 200)
        est = cm.estimate_tokens()
        assert est > 1000


class TestNeedsSummarization:
    def test_short_history(self):
        cm = ConversationManager(token_limit=100000)
        cm.append("user", "hi")
        cm.append("assistant", "hello")
        assert cm.needs_summarization() is False

    def test_exceeds_limit(self):
        cm = ConversationManager(token_limit=100)
        cm.append("user", "x" * 500)  # ~250 tokens
        cm.append("assistant", "y" * 500)
        cm.append("user", "x" * 500)  # need > 2 messages to check
        assert cm.needs_summarization() is True

    def test_skip_next_check(self):
        cm = ConversationManager(token_limit=10)
        cm._skip_next_token_check = True
        cm.append("user", "x" * 1000)
        cm.append("assistant", "y" * 1000)
        assert cm.needs_summarization() is False
        assert cm._skip_next_token_check is False  # flag reset


class TestSummarize:
    def test_trivial_history(self):
        cm = ConversationManager(token_limit=100000)
        cm.append("user", "hi")
        result = cm.summarize()
        assert result is None

    def test_summarize_execution_blocks(self):
        cm = ConversationManager(token_limit=100)
        cm.append("user", "initial context")
        cm.append("user", "Do a complex task")
        # Multi-message execution block (3 assistant messages between user messages)
        cm.append("assistant", [
            {"type": "tool_use", "id": "1", "name": "search", "input": {}},
        ])
        cm.append("assistant", "Let me search for that")
        cm.append("assistant", [
            {"type": "tool_use", "id": "2", "name": "read", "input": {}},
        ])
        cm.append("user", "x" * 500)
        cm.append("assistant", "y" * 500)
        cm.append("user", "x" * 500)
        original_len = cm.len()
        result = cm.summarize()
        assert result is not None
        assert cm.len() < original_len
        # First message + user messages survive
        assert cm.history[0]["role"] == "user"

    def test_user_messages_preserved(self):
        cm = ConversationManager(token_limit=100)
        cm.append("user", "initial")
        cm.append("user", "what time is it?")
        cm.append("assistant", [
            {"type": "tool_use", "id": "1", "name": "get_time", "input": {}},
        ])
        cm.append("user", [
            {"type": "tool_result", "tool_use_id": "1", "content": "12:00"},
        ])
        cm.append("assistant", "It is noon")
        cm.summarize()
        user_msgs = [m for m in cm.history if m.get("role") == "user"]
        assert len(user_msgs) >= 2


class TestTrimToTokenBudget:
    def test_within_budget(self):
        cm = ConversationManager(token_limit=100000)
        cm.append("user", "hi")
        cm.append("assistant", "hello")
        removed = cm.trim_to_token_budget(keep_last=4)
        assert removed == 0

    def test_exceeds_budget(self):
        cm = ConversationManager(token_limit=100)
        for i in range(20):
            cm.append("user", f"msg {i} " + "x" * 200)
            cm.append("assistant", "y" * 200)
        removed = cm.trim_to_token_budget(keep_last=4)
        assert removed > 0
        assert cm.len() < 40  # substantially trimmed


class TestKeepFirstAndLast:
    def test_no_trim_needed(self):
        cm = ConversationManager()
        cm.append("user", "a")
        cm.append("assistant", "b")
        removed = cm.keep_first_and_last(keep_last=8)
        assert removed == 0

    def test_trim(self):
        cm = ConversationManager()
        for i in range(30):
            cm.append("user", f"msg{i}")
            cm.append("assistant", f"reply{i}")
        removed = cm.keep_first_and_last(keep_last=8)
        assert removed > 0
        assert cm.history[0]["content"] == "msg0"  # first preserved

    def test_safe_boundary_preserved(self):
        """Tool pairs should not be broken across trim boundary."""
        cm = ConversationManager()
        cm.append("user", "system")
        for i in range(5):
            cm.append("user", f"request {i}")
            cm.append("assistant", [
                {"type": "tool_use", "id": f"t{i}", "name": "search", "input": {}},
            ])
            cm.append("user", [
                {"type": "tool_result", "tool_use_id": f"t{i}", "content": f"result {i}"},
            ])
        removed = cm.keep_first_and_last(keep_last=6)
        assert removed > 0
        # Verify no orphaned tool_results
        for msg in cm.history:
            content = msg.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        # The tool_use_id should be present in history
                        ref_id = block.get("tool_use_id")
                        found = False
                        for m in cm.history:
                            mc = m.get("content", "")
                            if isinstance(mc, list):
                                for b in mc:
                                    if isinstance(b, dict) and b.get("type") == "tool_use":
                                        if b.get("id") == ref_id:
                                            found = True
                        assert found, f"Orphaned tool_result referencing {ref_id}"
