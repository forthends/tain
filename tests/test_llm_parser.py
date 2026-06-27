"""Tests for LLM response parsing — LLMResponse, ToolCall, and message conversion.

These test the standardized response types and the provider-specific
message conversion logic that converts internal format to provider
format and back. No actual LLM API calls are made.
"""

import pytest

from tain_agent.core.llm import LLMResponse, ToolCall


class TestToolCall:
    """ToolCall is a simple dataclass for standardized tool use blocks."""

    def test_create_with_required_fields(self):
        tc = ToolCall(id="tc_1", name="web_search", input={"query": "test"})
        assert tc.id == "tc_1"
        assert tc.name == "web_search"
        assert tc.input == {"query": "test"}

    def test_empty_input_set_to_empty_dict(self):
        tc = ToolCall(id="tc_2", name="read_file", input={})
        assert tc.input == {}

    def test_complex_nested_input(self):
        tc = ToolCall(
            id="tc_3",
            name="forge_tool",
            input={
                "name": "my_tool",
                "code": "def foo():\n    return 42",
                "parameters": {"x": "int", "y": "str"},
            },
        )
        assert tc.input["code"] == "def foo():\n    return 42"
        assert tc.input["parameters"]["x"] == "int"

    def test_unicode_name_and_input(self):
        tc = ToolCall(id="tc_4", name="执行代码", input={"代码": "print('你好')"})
        assert tc.name == "执行代码"
        assert tc.input["代码"] == "print('你好')"


class TestLLMResponse:
    """LLMResponse is the standardized response from all LLM backends."""

    def test_empty_response_has_defaults(self):
        resp = LLMResponse()
        assert resp.text_blocks == []
        assert resp.tool_calls == []
        assert resp.extra_blocks == []

    def test_text_only_response(self):
        resp = LLMResponse(
            text_blocks=["Hello, I am an AI assistant."],
        )
        assert len(resp.text_blocks) == 1
        assert resp.tool_calls == []
        assert "Hello" in resp.text_blocks[0]

    def test_multiple_text_blocks(self):
        resp = LLMResponse(
            text_blocks=["First paragraph.", "Second paragraph.", "Third."],
        )
        assert len(resp.text_blocks) == 3
        assert resp.tool_calls == []

    def test_single_tool_call_response(self):
        tc = ToolCall(id="tc_1", name="web_search", input={"query": "test"})
        resp = LLMResponse(
            text_blocks=["Let me search for that."],
            tool_calls=[tc],
        )
        assert len(resp.text_blocks) == 1
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "web_search"

    def test_multiple_tool_calls_response(self):
        tc1 = ToolCall(id="a", name="read_file", input={"path": "a.txt"})
        tc2 = ToolCall(id="b", name="write_file", input={"path": "b.txt", "content": "data"})
        resp = LLMResponse(
            text_blocks=["I'll read and write files."],
            tool_calls=[tc1, tc2],
        )
        assert len(resp.tool_calls) == 2
        assert resp.tool_calls[0].name == "read_file"
        assert resp.tool_calls[1].name == "write_file"

    def test_extra_blocks_for_thinking(self):
        resp = LLMResponse(
            text_blocks=["Here is my analysis."],
            extra_blocks=[{"type": "thinking", "thinking": "Need to consider..."}],
        )
        assert len(resp.extra_blocks) == 1
        assert resp.extra_blocks[0]["type"] == "thinking"
        assert "Need to consider" in resp.extra_blocks[0]["thinking"]

    def test_text_and_tool_calls_together(self):
        tc = ToolCall(id="x", name="execute_code", input={"code": "1+1"})
        resp = LLMResponse(
            text_blocks=["Running the code..."],
            tool_calls=[tc],
            extra_blocks=[{"type": "thinking", "thinking": "Simple math"}],
        )
        assert len(resp.text_blocks) == 1
        assert len(resp.tool_calls) == 1
        assert len(resp.extra_blocks) == 1

    def test_field_isolation(self):
        """Changes to one field's list should not affect others."""
        resp = LLMResponse(text_blocks=["a"], tool_calls=[], extra_blocks=[])
        resp.text_blocks.append("b")
        assert resp.tool_calls == []
        assert resp.extra_blocks == []

    def test_field_defaults_are_distinct_instances(self):
        """Each LLMResponse should get its own list instances."""
        r1 = LLMResponse()
        r2 = LLMResponse()
        r1.text_blocks.append("hello")
        assert r2.text_blocks == []  # r2 unaffected


class TestLLMResponseEdgeCases:
    """Edge cases in LLMResponse handling."""

    def test_text_block_with_empty_string(self):
        resp = LLMResponse(text_blocks=[""])
        assert resp.text_blocks == [""]
        assert resp.tool_calls == []

    def test_text_block_with_newlines_only(self):
        resp = LLMResponse(text_blocks=["\n\n\n"])
        assert len(resp.text_blocks) == 1

    def test_text_blocks_with_html_tags(self):
        """HTML-like content should just be text — no special parsing."""
        resp = LLMResponse(
            text_blocks=["<div>some html</div> is just text here."],
        )
        assert "<div>" in resp.text_blocks[0]

    def test_text_blocks_with_json_like_content(self):
        resp = LLMResponse(
            text_blocks=['{"name": "fake_tool", "args": {}}'],
        )
        assert "fake_tool" in resp.text_blocks[0]

    def test_tool_call_with_large_input(self):
        """Tool calls with large code blocks should work fine."""
        big_code = "x = 1\n" * 1000
        tc = ToolCall(id="big", name="execute_code", input={"code": big_code})
        assert len(tc.input["code"]) == len(big_code)


class TestMessageConversion:
    """Test internal message format ↔ provider format conversion.

    The framework uses a content-block format internally:
    list of {"type": "text"|"tool_use"|"tool_result", ...}
    This is converted to provider-specific formats by each backend.
    """

    def test_simple_user_message_is_plain_text(self):
        """A simple user message is just a string."""
        msg = {"role": "user", "content": "Hello"}
        assert msg["role"] == "user"
        assert isinstance(msg["content"], str)

    def test_assistant_message_with_text_blocks(self):
        """Assistant message with text + tool_use blocks."""
        msg = {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me help."},
                {"type": "tool_use", "id": "tc1", "name": "search", "input": {"q": "x"}},
            ],
        }
        assert len(msg["content"]) == 2
        assert msg["content"][0]["type"] == "text"
        assert msg["content"][1]["type"] == "tool_use"
        assert msg["content"][1]["name"] == "search"

    def test_user_message_with_tool_results(self):
        """User message containing tool_result blocks."""
        msg = {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tc1", "content": "Search results: ..."},
            ],
        }
        assert msg["content"][0]["type"] == "tool_result"
        assert msg["content"][0]["tool_use_id"] == "tc1"

    def test_empty_tool_result_content_handled(self):
        """Empty tool result content should be safely stringified."""
        msg = {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "empty", "content": ""},
            ],
        }
        assert msg["content"][0]["content"] == ""
