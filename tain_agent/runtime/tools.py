"""
Tool System — registration, execution, and timeout protection.

Zero framework dependencies. Designed to be copied into exported agents.
"""

import json
import signal
import traceback
from typing import Optional, Callable


class ToolTimeout(Exception):
    """Raised when a tool exceeds its execution time limit."""


class ToolRegistry:
    """Registry for callable tools with schema definitions.

    Each tool entry:
        name: str          — unique identifier
        fn: Callable       — the implementation
        schema: dict       — Anthropic-format tool definition
        timeout_seconds: int — max execution time (default 30)
    """

    def __init__(self):
        self._tools: dict[str, dict] = {}

    def register(self, name: str, fn: Callable, schema: dict,
                 timeout_seconds: int = 30) -> None:
        self._tools[name] = {
            "fn": fn,
            "schema": schema,
            "timeout_seconds": timeout_seconds,
        }

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get_schemas(self) -> list[dict]:
        """Return Anthropic-format tool definitions for all registered tools."""
        return [t["schema"] for t in self._tools.values()]

    def list_names(self) -> list[str]:
        return sorted(self._tools.keys())

    def has(self, name: str) -> bool:
        return name in self._tools

    def execute(self, name: str, input_data: dict,
                timeout_seconds: Optional[int] = None) -> dict:
        """Execute a tool by name with the given input.

        Returns a tool_result content block (Anthropic format).
        On timeout, returns an error block.
        """
        if name not in self._tools:
            return {
                "type": "tool_result",
                "tool_use_id": input_data.get("tool_use_id", ""),
                "content": json.dumps({"error": f"Tool not found: {name}"}),
                "is_error": True,
            }

        tool = self._tools[name]
        timeout = timeout_seconds or tool["timeout_seconds"]
        tool_use_id = input_data.get("tool_use_id", "")

        # Strip tool_use_id from input before passing to fn
        fn_input = {k: v for k, v in input_data.items() if k != "tool_use_id"}

        try:
            result = _run_with_timeout(tool["fn"], fn_input, timeout)
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps(result) if not isinstance(result, str) else result,
            }
        except ToolTimeout:
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps({
                    "error": f"Tool '{name}' timed out after {timeout}s",
                }),
                "is_error": True,
            }
        except Exception as exc:
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps({
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }),
                "is_error": True,
            }


def _run_with_timeout(fn: Callable, input_data: dict, timeout_seconds: int):
    """Run fn(*input_data values) with a timeout.

    Uses signal.alarm on Unix; falls back to direct call on Windows.
    """
    if not hasattr(signal, "SIGALRM"):
        return fn(**input_data)

    def _handler(signum, frame):
        raise ToolTimeout()

    old_handler = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout_seconds)
    try:
        return fn(**input_data)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
