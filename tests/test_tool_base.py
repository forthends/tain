"""Tests for tain_agent.tools.base"""

import pytest
from tain_agent.tools.base import Tool, _sanitize_json_schema
from tain_agent.tools.registry import ToolRegistry


class ConcreteTool(Tool):
    name = "concrete_tool"
    description = "A test tool"
    parameters = {
        "text": {"type": "string", "description": "Input text", "required": True},
        "count": {"type": "integer", "description": "Repeat count", "required": False},
    }

    def execute(self, text: str = "", count: int = 1, **kwargs):
        return {"text": text, "repeated": text * count}


class TestTool:
    def test_to_schema(self):
        tool = ConcreteTool()
        schema = tool.to_schema()
        assert schema["name"] == "concrete_tool"
        assert schema["description"] == "A test tool"
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"

    def test_to_schema_properties(self):
        tool = ConcreteTool()
        schema = tool.to_schema()
        props = schema["input_schema"]["properties"]
        assert "text" in props
        assert props["text"]["type"] == "string"
        assert "count" in props
        assert props["count"]["type"] == "integer"

    def test_to_openai_schema(self):
        tool = ConcreteTool()
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "concrete_tool"

    def test_execute(self):
        tool = ConcreteTool()
        result = tool.execute(text="hi", count=3)
        assert result["text"] == "hi"
        assert result["repeated"] == "hihihi"

    def test_callable(self):
        tool = ConcreteTool()
        result = tool(text="hello", count=2)
        assert result["repeated"] == "hellohello"

    def test_register_on_registry(self):
        reg = ToolRegistry()
        tool = ConcreteTool()
        tool.register_on(reg)
        assert reg.has("concrete_tool")

    def test_no_parameters(self):
        class BareTool(Tool):
            name = "bare"
            description = "No params"
            def execute(self, **kwargs):
                return kwargs

        tool = BareTool()
        schema = tool.to_schema()
        assert schema["input_schema"]["type"] == "object"

    def test_json_schema_parameters(self):
        class SchemaTool(Tool):
            name = "schema_tool"
            description = "JSON Schema params"
            parameters = {
                "type": "object",
                "properties": {
                    "x": {"type": "number", "description": "A number"},
                },
                "required": ["x"],
            }
            def execute(self, **kwargs):
                return kwargs

        tool = SchemaTool()
        schema = tool.to_schema()
        props = schema["input_schema"]["properties"]
        assert props["x"]["type"] == "number"


class TestSanitizeJsonSchema:
    def test_valid_types_passthrough(self):
        schema = {"type": "string", "properties": {"x": {"type": "integer"}}}
        result = _sanitize_json_schema(schema)
        assert result == schema

    def test_invalid_type_fixed(self):
        schema = {"type": "Any"}
        result = _sanitize_json_schema(schema)
        assert result["type"] == "string"

    def test_list_type_fixed(self):
        schema = {"type": "List[str]"}
        result = _sanitize_json_schema(schema)
        assert result["type"] == "array"

    def test_dict_type_fixed(self):
        schema = {"type": "Dict[str, int]"}
        result = _sanitize_json_schema(schema)
        assert result["type"] == "object"

    def test_nested_invalid_types(self):
        schema = {
            "type": "object",
            "properties": {
                "items": {"type": "List[int]", "items": {"type": "Any"}},
            },
        }
        result = _sanitize_json_schema(schema)
        assert result["properties"]["items"]["type"] == "array"
        assert result["properties"]["items"]["items"]["type"] == "string"
