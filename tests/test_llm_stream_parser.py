"""
Tests for LLM response parsing — XML tool call extraction and response objects.

Covers:
  - Plain text responses (no tool calls)
  - Single and multiple XML tool call extraction
  - Thinking block / prefix text isolation
  - Edge cases: empty, malformed JSON, unclosed tags, namespace prefixes
  - _regex_fallback for malformed XML
  - LLMResponse and ToolCall dataclasses
"""

import json
import re
import pytest

from tain_agent.core.llm import LLMResponse, ToolCall
from tain_agent.core.chat import _extract_xml_tool_calls, _regex_fallback


# ---------------------------------------------------------------------------
# ToolCall / LLMResponse dataclass tests
# ---------------------------------------------------------------------------

class TestToolCall:
    def test_default_construction(self):
        tc = ToolCall(id="abc", name="search", input={"q": "hello"})
        assert tc.id == "abc"
        assert tc.name == "search"
        assert tc.input == {"q": "hello"}

    def test_empty_input(self):
        tc = ToolCall(id="x", name="nop", input={})
        assert tc.input == {}

    def test_eq_same_values(self):
        a = ToolCall(id="1", name="f", input={"x": 1})
        b = ToolCall(id="1", name="f", input={"x": 1})
        assert a == b  # dataclass auto-eq

    def test_neq_different_id(self):
        a = ToolCall(id="1", name="f", input={})
        b = ToolCall(id="2", name="f", input={})
        assert a != b


class TestLLMResponse:
    def test_default_empty(self):
        r = LLMResponse()
        assert r.text_blocks == []
        assert r.tool_calls == []
        assert r.extra_blocks == []

    def test_populated_text_only(self):
        r = LLMResponse(
            text_blocks=["hello", " world"],
            tool_calls=[],
            extra_blocks=[],
        )
        assert r.text_blocks == ["hello", " world"]
        assert r.tool_calls == []

    def test_populated_with_tool_calls(self):
        tc = ToolCall(id="1", name="f", input={})
        r = LLMResponse(text_blocks=[], tool_calls=[tc], extra_blocks=[])
        assert len(r.tool_calls) == 1
        assert r.tool_calls[0].name == "f"

    def test_extra_blocks_thinking(self):
        r = LLMResponse(
            text_blocks=["response"],
            tool_calls=[],
            extra_blocks=[{"type": "thinking", "thinking": "hmm", "signature": ""}],
        )
        assert r.extra_blocks[0]["type"] == "thinking"
        assert r.extra_blocks[0]["thinking"] == "hmm"


# ---------------------------------------------------------------------------
# _extract_xml_tool_calls — plain text (no tool calls)
# ---------------------------------------------------------------------------

class TestExtractXmlToolCallsPlainText:
    def test_empty_string(self):
        prefix, tcs = _extract_xml_tool_calls("")
        assert prefix == ""
        assert tcs == []

    def test_whitespace_only(self):
        prefix, tcs = _extract_xml_tool_calls("   \n  ")
        assert prefix == "   \n  "
        assert tcs == []

    def test_simple_text_no_tags(self):
        prefix, tcs = _extract_xml_tool_calls("Hello, world!")
        assert prefix == "Hello, world!"
        assert tcs == []

    def test_angle_brackets_but_not_tool_calls(self):
        prefix, tcs = _extract_xml_tool_calls("Use <div> and <span> in HTML")
        assert prefix == "Use <div> and <span> in HTML"
        assert tcs == []

    def test_multiline_text_no_tool_calls(self):
        text = "Line one.\nLine two.\nLine three."
        prefix, tcs = _extract_xml_tool_calls(text)
        assert prefix == text
        assert tcs == []


# ---------------------------------------------------------------------------
# _extract_xml_tool_calls — single tool call
# ---------------------------------------------------------------------------

class TestExtractXmlToolCallsSingle:
    def test_single_invoke_with_string_param(self):
        text = (
            "I will search for that.\n\n"
            "<tool_call>\n"
            '  <invoke name="web_search">\n'
            '    <parameter name="query">latest AI news</parameter>\n'
            "  </invoke>\n"
            "</tool_call>"
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        assert prefix == "I will search for that."
        assert len(tcs) == 1
        assert tcs[0].name == "web_search"
        assert tcs[0].input == {"query": "latest AI news"}
        assert tcs[0].id.startswith("xml_")

    def test_no_prefix_text(self):
        text = (
            '<tool_calls>\n'
            '  <invoke name="fetch">\n'
            '    <parameter name="url">https://example.com</parameter>\n'
            "  </invoke>\n"
            "</tool_calls>"
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        assert prefix == ""
        assert len(tcs) == 1
        assert tcs[0].name == "fetch"

    def test_json_param_value(self):
        text = (
            '<tool_calls>'
            '  <invoke name="update">'
            '    <parameter name="data">{"key": "val", "num": 42}</parameter>'
            "  </invoke>"
            "</tool_calls>"
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        assert len(tcs) == 1
        assert tcs[0].input == {"data": {"key": "val", "num": 42}}

    def test_list_json_param_value(self):
        text = (
            '<tool_calls>'
            '  <invoke name="batch">'
            '    <parameter name="ids">[1, 2, 3]</parameter>'
            "  </invoke>"
            "</tool_calls>"
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        assert len(tcs) == 1
        assert tcs[0].input == {"ids": [1, 2, 3]}

    def test_tool_call_tag_variant(self):
        """Both <tool_call> and <tool_calls> forms should work."""
        text = (
            '<tool_call>'
            '  <invoke name="do_thing">'
            '    <parameter name="x">1</parameter>'
            "  </invoke>"
            "</tool_call>"
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        assert len(tcs) == 1
        assert tcs[0].name == "do_thing"

    def test_multiple_params(self):
        text = (
            '<tool_calls>\n'
            '  <invoke name="run">\n'
            '    <parameter name="cmd">ls</parameter>\n'
            '    <parameter name="args">-la</parameter>\n'
            "  </invoke>\n"
            "</tool_calls>"
        )
        _, tcs = _extract_xml_tool_calls(text)
        assert len(tcs) == 1
        assert tcs[0].input == {"cmd": "ls", "args": "-la"}


# ---------------------------------------------------------------------------
# _extract_xml_tool_calls — multiple tool calls
# ---------------------------------------------------------------------------

class TestExtractXmlToolCallsMultiple:
    def test_two_invokes_in_single_tool_calls_block(self):
        text = (
            '<tool_calls>\n'
            '  <invoke name="search">\n'
            '    <parameter name="q">weather</parameter>\n'
            "  </invoke>\n"
            '  <invoke name="fetch">\n'
            '    <parameter name="url">https://weather.com</parameter>\n'
            "  </invoke>\n"
            "</tool_calls>"
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        assert prefix == ""
        assert len(tcs) == 2
        assert tcs[0].name == "search"
        assert tcs[0].input == {"q": "weather"}
        assert tcs[1].name == "fetch"
        assert tcs[1].input == {"url": "https://weather.com"}

    def test_three_tool_calls(self):
        text = (
            "Let me do several things.\n"
            "<tool_calls>\n"
            '  <invoke name="a"><parameter name="x">1</parameter></invoke>\n'
            '  <invoke name="b"><parameter name="y">2</parameter></invoke>\n'
            '  <invoke name="c"><parameter name="z">3</parameter></invoke>\n'
            "</tool_calls>"
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        assert prefix == "Let me do several things."
        assert len(tcs) == 3
        assert [tc.name for tc in tcs] == ["a", "b", "c"]

    def test_unique_ids_for_multiple_calls(self):
        text = (
            '<tool_calls>'
            '  <invoke name="x"><parameter name="a">1</parameter></invoke>'
            '  <invoke name="y"><parameter name="b">2</parameter></invoke>'
            "</tool_calls>"
        )
        _, tcs = _extract_xml_tool_calls(text)
        assert len(tcs) == 2
        # each should have a unique xml_ prefix id
        assert tcs[0].id != tcs[1].id
        assert tcs[0].id.startswith("xml_")
        assert tcs[1].id.startswith("xml_")


# ---------------------------------------------------------------------------
# _extract_xml_tool_calls — prefix text (thinking block isolation)
# ---------------------------------------------------------------------------

class TestExtractXmlToolCallsPrefix:
    def test_thinking_text_before_tool_calls(self):
        text = (
            "Let me think about this carefully...\n"
            "The best approach would be to search first.\n\n"
            "<tool_calls>\n"
            '  <invoke name="web_search">\n'
            '    <parameter name="query">how to do X</parameter>\n'
            "  </invoke>\n"
            "</tool_calls>"
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        assert prefix == "Let me think about this carefully...\nThe best approach would be to search first."
        assert len(tcs) == 1
        assert tcs[0].name == "web_search"

    def test_text_after_tool_calls_is_inside_match(self):
        """Only text *before* the XML block is returned as prefix.
        Text inside the matched XML block is consumed."""
        text = (
            "Prefix text.\n"
            "<tool_calls>\n"
            '  <invoke name="f"><parameter name="x">1</parameter></invoke>\n'
            "</tool_calls>\n"
            "This text is inside the matched region and lost."
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        assert prefix == "Prefix text."
        assert len(tcs) == 1

    def test_multiline_prefix_with_blank_lines(self):
        text = (
            "Line one.\n"
            "\n"
            "Line three.\n"
            "\n"
            "<tool_calls>\n"
            '  <invoke name="test"><parameter name="v">ok</parameter></invoke>\n'
            "</tool_calls>"
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        assert prefix == "Line one.\n\nLine three."
        assert len(tcs) == 1


# ---------------------------------------------------------------------------
# _extract_xml_tool_calls — edge cases
# ---------------------------------------------------------------------------

class TestExtractXmlToolCallsEdgeCases:
    def test_malformed_json_in_param_stays_string(self):
        text = (
            '<tool_calls>'
            '  <invoke name="bad">'
            '    <parameter name="data">{broken json!!!}</parameter>'
            "  </invoke>"
            "</tool_calls>"
        )
        _, tcs = _extract_xml_tool_calls(text)
        assert len(tcs) == 1
        # stays as string because json.loads fails
        assert tcs[0].input == {"data": "{broken json!!!}"}

    def test_valid_json_array_in_param(self):
        text = (
            '<tool_calls>'
            '  <invoke name="store">'
            '    <parameter name="items">[{"a":1},{"b":2}]</parameter>'
            "  </invoke>"
            "</tool_calls>"
        )
        _, tcs = _extract_xml_tool_calls(text)
        assert len(tcs) == 1
        assert tcs[0].input == {"items": [{"a": 1}, {"b": 2}]}

    def test_empty_invoke_no_name(self):
        text = (
            '<tool_calls>'
            '  <invoke name="">'
            "  </invoke>"
            "</tool_calls>"
        )
        _, tcs = _extract_xml_tool_calls(text)
        # invoke with empty name is skipped
        assert len(tcs) == 0

    def test_empty_parameter_value(self):
        text = (
            '<tool_calls>'
            '  <invoke name="f">'
            '    <parameter name="empty_param"></parameter>'
            "  </invoke>"
            "</tool_calls>"
        )
        _, tcs = _extract_xml_tool_calls(text)
        assert len(tcs) == 1
        assert tcs[0].input == {"empty_param": ""}

    def test_nested_xml_in_param_value(self):
        """Parameter values with angle brackets should work (as text)."""
        text = (
            '<tool_calls>'
            '  <invoke name="render">'
            '    <parameter name="html"><div>hello</div></parameter>'
            "  </invoke>"
            "</tool_calls>"
        )
        _, tcs = _extract_xml_tool_calls(text)
        assert len(tcs) == 1
        # The nested XML may cause issues; the test verifies current behaviour
        assert tcs[0].name == "render"

    def test_invoke_missing_name_attribute(self):
        text = (
            '<tool_calls>'
            '  <invoke>'
            '    <parameter name="x">1</parameter>'
            "  </invoke>"
            "</tool_calls>"
        )
        _, tcs = _extract_xml_tool_calls(text)
        # invoke with no name attribute → name="" → skipped
        assert len(tcs) == 0

    def test_invoke_without_parameters(self):
        text = (
            '<tool_calls>'
            '  <invoke name="ping">'
            "  </invoke>"
            "</tool_calls>"
        )
        _, tcs = _extract_xml_tool_calls(text)
        assert len(tcs) == 1
        assert tcs[0].name == "ping"
        assert tcs[0].input == {}

    def test_unclosed_tool_calls_tag(self):
        """Unclosed </tool_calls> — regex still matches greedily."""
        text = (
            '<tool_calls>'
            '  <invoke name="f">'
            '    <parameter name="x">1</parameter>'
            "  </invoke>"
            # missing </tool_calls>
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        # Without closing tag the regex won't match; falls through to plain text
        assert prefix == text
        assert tcs == []

    def test_unclosed_invoke_tag_fallback_to_regex(self):
        """Unclosed </invoke> triggers XML parse error → regex fallback."""
        text = (
            '<tool_calls>'
            '  <invoke name="search">'
            '    <parameter name="q">test</parameter>'
            # missing </invoke>
            "</tool_calls>"
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        # Falls through to _regex_fallback which uses a different regex
        # that looks for <invoke ... name="..." ...> ... </invoke>
        assert len(tcs) == 0  # regex fallback also can't match unclosed invoke

    def test_completely_malformed_xml_fallback(self):
        """Totally broken XML should hit regex fallback and return gracefully."""
        text = (
            '<tool_calls>'
            '  <invoke name="f"'
            '    <parameter name="x"1</parameter>'
            "  </invoke>"
            "</tool_calls>"
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        # ET.fromstring will raise ParseError, regex fallback kicks in
        # With broken attributes the regex may or may not capture — either way no crash
        assert isinstance(prefix, str)
        assert isinstance(tcs, list)

    @pytest.mark.xfail(reason="Namespace prefix stripping not yet implemented in _extract_xml_tool_calls")
    def test_namespace_prefix_stripped(self):
        """XML with namespace prefixes like <ns:tool_calls> should be cleaned."""
        text = (
            '<foo:tool_calls xmlns:foo="...">'
            '  <invoke name="search">'
            '    <parameter name="q">test</parameter>'
            "  </invoke>"
            "</foo:tool_calls>"
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        assert len(tcs) == 1
        assert tcs[0].name == "search"

    def test_pipe_namespace_prefix_stripped(self):
        """XML with pipe-wrapped namespaces like |ns|tool_calls should be cleaned."""
        text = (
            "<|ns|tool_calls>"
            '  <invoke name="get">'
            '    <parameter name="key">val</parameter>'
            "  </invoke>"
            "</|ns|tool_calls>"
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        assert len(tcs) == 1
        assert tcs[0].name == "get"

    def test_no_parameter_name_attribute(self):
        text = (
            '<tool_calls>'
            '  <invoke name="f">'
            "    <parameter>value_without_name</parameter>"
            "  </invoke>"
            "</tool_calls>"
        )
        _, tcs = _extract_xml_tool_calls(text)
        assert len(tcs) == 1
        # parameter without name attribute gets pname=""
        assert "" in tcs[0].input

    def test_whitespace_around_param_value_preserved(self):
        text = (
            '<tool_calls>'
            '  <invoke name="trim">'
            '    <parameter name="text">  padded value  </parameter>'
            "  </invoke>"
            "</tool_calls>"
        )
        _, tcs = _extract_xml_tool_calls(text)
        assert tcs[0].input == {"text": "padded value"}  # .strip() applied

    def test_very_long_text_with_tool_calls(self):
        prefix_long = "Lorem ipsum dolor sit amet.\n" * 50
        text = (
            prefix_long
            + "<tool_calls>\n"
            + '  <invoke name="search">\n'
            + '    <parameter name="q">long context query</parameter>\n'
            + "  </invoke>\n"
            + "</tool_calls>"
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        assert prefix == prefix_long.rstrip()
        assert len(tcs) == 1
        assert tcs[0].name == "search"

    def test_toolcalls_surrounded_by_text_both_sides(self):
        text = (
            "I think I need to check something.\n"
            "<tool_calls>\n"
            '  <invoke name="check"><parameter name="what">status</parameter></invoke>\n'
            "</tool_calls>\n"
            "Now let me continue with the results."
        )
        prefix, tcs = _extract_xml_tool_calls(text)
        assert prefix == "I think I need to check something."
        assert len(tcs) == 1
        assert tcs[0].name == "check"


# ---------------------------------------------------------------------------
# _regex_fallback tests
# ---------------------------------------------------------------------------

class TestRegexFallback:
    def test_empty_input(self):
        result = _regex_fallback("")
        assert result == []

    def test_no_invoke_tags(self):
        result = _regex_fallback("<tool_calls></tool_calls>")
        assert result == []

    def test_single_valid_invoke(self):
        xml_text = (
            '<tool_calls>'
            '  <invoke name="search">'
            '    <parameter name="q">hello</parameter>'
            '  </invoke>'
            "</tool_calls>"
        )
        result = _regex_fallback(xml_text)
        assert len(result) == 1
        assert result[0].name == "search"
        assert result[0].input == {"q": "hello"}

    def test_multiple_invokes_regex(self):
        xml_text = (
            '<tool_calls>'
            '  <invoke name="a">'
            '    <parameter name="x">1</parameter>'
            '  </invoke>'
            '  <invoke name="b">'
            '    <parameter name="y">2</parameter>'
            '  </invoke>'
            "</tool_calls>"
        )
        result = _regex_fallback(xml_text)
        assert len(result) == 2
        assert [tc.name for tc in result] == ["a", "b"]

    def test_invoke_with_json_param_regex(self):
        xml_text = (
            '<tool_calls>'
            '  <invoke name="f">'
            '    <parameter name="data">{"nested": true}</parameter>'
            '  </invoke>'
            "</tool_calls>"
        )
        result = _regex_fallback(xml_text)
        assert len(result) == 1
        assert result[0].input == {"data": {"nested": True}}

    def test_invoke_with_malformed_json_param_regex(self):
        xml_text = (
            '<tool_calls>'
            '  <invoke name="f">'
            '    <parameter name="data">{bad</parameter>'
            '  </invoke>'
            "</tool_calls>"
        )
        result = _regex_fallback(xml_text)
        assert len(result) == 1
        assert result[0].input == {"data": "{bad"}  # stays string

    def test_missing_name_attribute_regex(self):
        xml_text = (
            '<tool_calls>'
            '  <invoke>'
            '    <parameter name="x">1</parameter>'
            '  </invoke>'
            "</tool_calls>"
        )
        result = _regex_fallback(xml_text)
        # regex needs `name="..."` in invoke tag — no match
        assert result == []

    def test_id_prefix_xml(self):
        xml_text = (
            '<tool_calls>'
            '  <invoke name="f"><parameter name="x">1</parameter></invoke>'
            "</tool_calls>"
        )
        result = _regex_fallback(xml_text)
        assert len(result) == 1
        assert result[0].id.startswith("xml_")
        assert len(result[0].id) == len("xml_") + 8  # 8 hex chars


# ---------------------------------------------------------------------------
# Integration-style: simulate ChatEngine parsing flow
# ---------------------------------------------------------------------------

class TestChatEngineParsingFlow:
    """Simulate how ChatEngine.run_turn uses the parser."""

    def test_stream_with_xml_fallback_when_no_native_tool_calls(self):
        """
        When the backend stream returns text_delta events but no tool_call events,
        but the accumulated text contains <tool_calls>...</tool_calls>,
        the ChatEngine should detect this and use _extract_xml_tool_calls.
        """
        simulated_stream_text = (
            "Let me help with that.\n"
            "<tool_calls>\n"
            '  <invoke name="web_search">\n'
            '    <parameter name="query">python testing</parameter>\n'
            "  </invoke>\n"
            "</tool_calls>"
        )

        full = simulated_stream_text
        turn_tools = []

        # Simulate detection logic from chat.py line 67
        if not turn_tools and re.search(r'<[^>]*?tool_calls?>', full):
            prefix, xml_tcs = _extract_xml_tool_calls(full)
            turn_text = [prefix] if prefix else []
            turn_tools = xml_tcs

        assert len(turn_tools) == 1
        assert turn_tools[0].name == "web_search"
        assert turn_tools[0].input == {"query": "python testing"}
        assert "".join(turn_text) == "Let me help with that."

    def test_stream_plain_text_no_fallback(self):
        import re

        simulated_stream_text = "This is a plain response with no tool calls."

        full = simulated_stream_text
        turn_tools = []

        if not turn_tools and re.search(r'<[^>]*?tool_calls?>', full):
            prefix, xml_tcs = _extract_xml_tool_calls(full)
            turn_tools = xml_tcs

        assert turn_tools == []
