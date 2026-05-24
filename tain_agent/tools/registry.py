"""
Tool Registry — 工具注册表

All tools the Tao Agent can use are registered here.
The registry is self-describing: the agent can query it to discover what it can do.
"""

import concurrent.futures
import traceback
import time as time_module
from typing import Callable, Optional

class ToolRegistry:
    """Extensible registry of tools the agent can discover and use.

    Safety: call() executes tools with a thread-pool timeout guard.
    Default timeout is 60s per tool call.
    """

    # Tools known to need longer execution (network, heavy compute)
    _EXTENDED_TIMEOUT_TOOLS = {"web_search", "web_fetch", "regression_tester"}

    def __init__(self, default_timeout: float = 60.0):
        self._tools: dict[str, dict] = {}
        self.default_timeout = default_timeout
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def register(self, name: str, func: Callable, description: str, parameters: dict = None) -> None:
        """Register a tool that the agent can use."""
        self._tools[name] = {
            "func": func,
            "description": description,
            "parameters": parameters or {},
        }

    def list_tools(self) -> dict[str, dict]:
        """List all registered tools with their metadata (not functions)."""
        return {
            name: {
                "description": info["description"],
                "parameters": info["parameters"],
            }
            for name, info in self._tools.items()
        }

    def call(self, tool_name: str, timeout: Optional[float] = None, **kwargs) -> dict:
        """Call a registered tool with timeout protection.

        Executes in a separate thread; if it exceeds the timeout,
        the call is cancelled and a structured error is returned.

        Args:
            tool_name: Name of the registered tool.
            timeout: Max seconds (None = use default, extended for network tools).
            **kwargs: Arguments passed to the tool function.
        """
        if tool_name not in self._tools:
            return {
                "success": False,
                "error": f"Tool '{tool_name}' not found. Available: {list(self._tools.keys())}",
                "error_type": "not_found",
            }

        if timeout is None:
            timeout = 120.0 if tool_name in self._EXTENDED_TIMEOUT_TOOLS else self.default_timeout

        func = self._tools[tool_name]["func"]
        started_at = time_module.perf_counter()

        try:
            future = self._executor.submit(func, **kwargs)
            result = future.result(timeout=timeout)
            elapsed_ms = (time_module.perf_counter() - started_at) * 1000
            return {
                "success": True,
                "result": result,
                "duration_ms": round(elapsed_ms, 2),
            }

        except concurrent.futures.TimeoutError:
            elapsed_ms = (time_module.perf_counter() - started_at) * 1000
            future.cancel()
            return {
                "success": False,
                "error": f"Tool '{tool_name}' exceeded {timeout}s timeout.",
                "error_type": "timeout",
                "duration_ms": round(elapsed_ms, 2),
            }

        except Exception as e:
            elapsed_ms = (time_module.perf_counter() - started_at) * 1000
            return {
                "success": False,
                "error": f"{type(e).__name__}: {str(e)}",
                "error_type": "exception",
                "traceback": traceback.format_exc(),
                "duration_ms": round(elapsed_ms, 2),
            }

    def remove(self, tool_name: str) -> bool:
        """Remove a tool from the registry."""
        if tool_name in self._tools:
            del self._tools[tool_name]
            return True
        return False

    def list_names(self) -> list[str]:
        """Return a sorted list of all registered tool names."""
        return sorted(self._tools.keys())

    def has(self, name: str) -> bool:
        """Check if a tool is registered by name. Returns True if found."""
        return name in self._tools

    def count(self) -> int:
        """Return the total number of registered tools."""
        return len(self._tools)

    def get_claude_tool_definitions(self) -> list[dict]:
        """Export tools in Claude API tool-use format."""
        definitions = []
        for name, info in self._tools.items():
            params = info.get("parameters", {})
            if not isinstance(params, dict):
                params = {}

            # Handle both flat format {param: {type, description}} and
            # JSON Schema format {"type": "object", "properties": {...}, "required": [...]}
            if "properties" in params:
                # JSON Schema format
                inner = params.get("properties", {})
                required = params.get("required", [])
                properties = {}
                for pname, pmeta in inner.items():
                    if isinstance(pmeta, dict):
                        properties[pname] = {
                            "type": pmeta.get("type", "string"),
                            "description": pmeta.get("description", ""),
                        }
                    else:
                        properties[pname] = {
                            "type": "string",
                            "description": str(pmeta),
                        }
            else:
                # Flat format
                properties = {}
                required = []
                for pname, pmeta in params.items():
                    if isinstance(pmeta, dict):
                        properties[pname] = {
                            "type": pmeta.get("type", "string"),
                            "description": pmeta.get("description", ""),
                        }
                        if pmeta.get("required", False):
                            required.append(pname)
                    elif isinstance(pmeta, str):
                        properties[pname] = {
                            "type": "string",
                            "description": pmeta,
                        }

            definitions.append({
                "name": name,
                "description": info.get("description", ""),
                "input_schema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            })
        return definitions
