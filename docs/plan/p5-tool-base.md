# P5 — Tool Base Class

**Target:** v0.4.5
**Source:** [design doc supplement, section 3](../design/v0-4-2-design.md#接口契约)

## Current State

`ToolRegistry` uses implicit contracts — `register(name, func, description, parameters)`. No enforced interface. When agent forges tools via `ToolForge`, there is no base class constraint → quality of generated tools is unpredictable.

## Reference (Mini-Agent)

```python
class Tool:
    name: str
    description: str
    parameters: dict       # JSON Schema
    execute(**kwargs)       # async
    to_schema()             # Anthropic format
    to_openai_schema()      # OpenAI format
```

## Implementation

### New file: `tain_agent/tools/base.py`

```python
from abc import ABC, abstractmethod

class Tool(ABC):
    """Base class all tools must implement."""

    name: str
    description: str
    parameters: dict = {}

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        ...

    def to_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _sanitize_json_schema(self.parameters),
            },
        }
```

### Modified files

- `tain_agent/tools/primal.py` — existing tools refactored to subclass `Tool`
- `tain_agent/tools/registry.py` — `register()` accepts both `Tool` instances and legacy functions (backward compat)
- `tain_agent/tools/forge.py` — `forge` command generates code that subclasses `Tool`

### Template for forged tools

```
from tain_agent.tools.base import Tool

class {ToolName}(Tool):
    name = "{tool_name}"
    description = "{description}"
    parameters = {json_schema}

    async def execute(self, **kwargs):
        # generated implementation
```

## Verification

- All existing tools still work after refactoring
- Newly forged tools inherit `to_schema()` / `to_openai_schema()` automatically
- Tool registry accepts both `Tool` subclasses and legacy functions
- Invalid forged tools (missing execute) fail at registration time, not at call time
