"""
Tool Base Class — interface contract for all agent tools.

Defines the standard Tool interface that every tool (primal, forged,
or dynamically loaded) must implement. This ensures consistent behavior
and reduces format errors when tools are created by the agent's forge.
"""

import json
from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Standard interface for all agent tools.

    Subclasses must define:
        name: str
        description: str
        execute(**kwargs) -> Any

    The base class provides automatic schema generation for Anthropic
    and OpenAI formats.
    """

    name: str = ""
    description: str = ""
    parameters: dict = {}

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        """Execute the tool. Subclasses override this."""
        ...

    # ── Schema generation ─────────────────────────────────────────

    def to_schema(self) -> dict:
        """Anthropic-format tool schema."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self._normalize_parameters(),
        }

    def to_openai_schema(self) -> dict:
        """OpenAI-format tool schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _sanitize_json_schema(self._normalize_parameters()),
            },
        }

    def _normalize_parameters(self) -> dict:
        """Convert flat or JSON Schema parameters into standard JSON Schema."""
        params = self.parameters
        if not isinstance(params, dict) or not params:
            return {"type": "object", "properties": {}}

        # Already JSON Schema format
        if "properties" in params:
            return params

        # Flat format: {name: {type, description, required}, ...}
        properties = {}
        required = []
        for pname, pmeta in params.items():
            if isinstance(pmeta, dict):
                properties[pname] = {
                    "type": pmeta.get("type", "string"),
                    "description": pmeta.get("description", ""),
                }
                if pmeta.get("required"):
                    required.append(pname)
            else:
                properties[pname] = {"type": "string", "description": str(pmeta)}

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    # ── Registry integration ──────────────────────────────────────

    def register_on(self, registry) -> None:
        """Register this tool instance on the given ToolRegistry."""
        registry.register_tool(self)

    # ── Callable protocol ─────────────────────────────────────────

    def __call__(self, **kwargs) -> Any:
        """Allow tool instances to be called like functions."""
        return self.execute(**kwargs)


# JSON Schema type sanitization for OpenAI (same as in llm.py)
_VALID_JSON_TYPES = {"string", "number", "integer", "boolean", "array", "object", "null"}


def _sanitize_json_schema(schema: dict) -> dict:
    """Recursively fix invalid JSON Schema types."""
    if not isinstance(schema, dict):
        return schema
    result = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str) and value not in _VALID_JSON_TYPES:
            if value.startswith("List") or value.startswith("list"):
                result[key] = "array"
            elif value.startswith("Dict") or value.startswith("dict"):
                result[key] = "object"
            else:
                result[key] = "string"
        elif key == "properties" and isinstance(value, dict):
            result[key] = {k: _sanitize_json_schema(v) for k, v in value.items()}
        elif key == "items" and isinstance(value, dict):
            result[key] = _sanitize_json_schema(value)
        elif key in ("anyOf", "oneOf", "allOf") and isinstance(value, list):
            result[key] = [_sanitize_json_schema(item) for item in value]
        else:
            result[key] = value
    return result
