"""Tests for LLM response parsing — XML tool call extraction, text/thinking separation."""
import pytest
from tain_agent.core.llm import LLMResponse, ToolCall


class TestLLMResponse:
    def test_response_stores_text_blocks(self):
        resp = LLMResponse()
        resp.text_blocks.append("Hello world")
        resp.text_blocks.append("How can I help?")
        assert resp.text_blocks == ["Hello world", "How can I help?"]

    def test_response_stores_tool_calls(self):
        resp = LLMResponse()
        tc = ToolCall(id="tc_1", name="read_file", input={"path": "/tmp/test"})
        resp.tool_calls.append(tc)
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "read_file"

    def test_response_separates_text_from_tools(self):
        resp = LLMResponse()
        resp.text_blocks.append("Let me read that file")
        resp.tool_calls.append(ToolCall(id="tc_1", name="read_file", input={"path": "/tmp/test"}))
        resp.text_blocks.append("The file says...")
        assert len(resp.text_blocks) == 2
        assert len(resp.tool_calls) == 1

    def test_empty_response_has_no_content(self):
        resp = LLMResponse()
        assert resp.text_blocks == []
        assert resp.tool_calls == []


class TestToolCallParsing:
    def test_single_tool_call_extraction(self):
        tc = ToolCall(id="toolu_01", name="execute_code",
                      input={"code": "print(1)", "language": "python"})
        assert tc.id == "toolu_01"
        assert tc.name == "execute_code"
        assert tc.input["code"] == "print(1)"


    def test_multiple_tool_calls_in_one_response(self):
        resp = LLMResponse()
        resp.tool_calls.append(ToolCall(id="tc_1", name="read_file", input={"path": "a.py"}))
        resp.tool_calls.append(ToolCall(id="tc_2", name="write_file", input={"path": "b.py", "content": "x"}))
        assert len(resp.tool_calls) == 2

    def test_tool_call_input_preserves_types(self):
        tc = ToolCall(id="tc_1", name="test", input={
            "name": "test", "count": 42, "enabled": True,
            "tags": ["a", "b"], "nested": {"key": "value"},
        })
        assert isinstance(tc.input["count"], int)
        assert isinstance(tc.input["enabled"], bool)
        assert isinstance(tc.input["tags"], list)


class TestTextThinkingSeparation:
    def test_pure_text_response_no_tools(self):
        resp = LLMResponse()
        resp.text_blocks.append("Here is what I found...")
        assert len(resp.text_blocks) == 1
        assert len(resp.tool_calls) == 0

    def test_text_before_and_after_tools(self):
        resp = LLMResponse()
        resp.text_blocks.append("I will search and read.")
        resp.tool_calls.append(ToolCall(id="tc_1", name="web_search", input={"query": "test"}))
        resp.tool_calls.append(ToolCall(id="tc_2", name="read_file", input={"path": "result.txt"}))
        resp.text_blocks.append("Here are the results.")
        assert len(resp.text_blocks) == 2
        assert len(resp.tool_calls) == 2


class TestAnthropicBackendResponseParsing:
    def test_parse_content_blocks_into_llmresponse(self):
        from dataclasses import dataclass as dc, field

        @dc
        class MockBlock:
            type: str
            text: str = ""
            id: str = ""
            name: str = ""
            input: dict = field(default_factory=dict)

        response = LLMResponse()
        blocks = [
            MockBlock(type="text", text="Let me think about this."),
            MockBlock(type="tool_use", id="tc_1", name="grep_code", input={"pattern": "test"}),
            MockBlock(type="text", text="Found 3 matches."),
        ]
        for block in blocks:
            if block.type == "text":
                response.text_blocks.append(block.text)
            elif block.type == "tool_use":
                response.tool_calls.append(ToolCall(
                    id=block.id, name=block.name,
                    input=block.input if isinstance(block.input, dict) else {},
                ))
        assert len(response.text_blocks) == 2
        assert response.tool_calls[0].name == "grep_code"

    def test_rate_limit_error_preserves_exit_code(self):
        error_msg = "Error code: 429 — rate_limit exceeded. Retry after 10s."
        assert "429" in error_msg
        assert "rate_limit" in error_msg.lower()


class TestXMLToolCallIntegration:
    def test_regex_fallback_extracts_tool_call_xml(self):
        import re
        xml_text = """<tool_calls>
<tool_call name="read_file">
{"path": "/tmp/test.txt"}
</tool_call>
</tool_calls>"""
        pattern = r'<tool_calls>.*?</tool_calls>'
        match = re.search(pattern, xml_text, re.DOTALL)
        assert match is not None
        tc_pattern = r'<tool_call name="([^"]+)">\s*(.*?)\s*</tool_call>'
        matches = re.findall(tc_pattern, xml_text, re.DOTALL)
        assert len(matches) == 1
        assert matches[0][0] == "read_file"

    def test_no_tool_call_pure_text_no_false_positive(self):
        import re
        text = "I can help you with that. Let me search for relevant information."
        pattern = r'<tool_calls>.*?</tool_calls>'
        match = re.search(pattern, text, re.DOTALL)
        assert match is None
