"""
LLM Backend Abstraction — 多模型支持

Supports:
- Anthropic (Claude)
- OpenAI
- DeepSeek (OpenAI-compatible)
- MiniMax (Anthropic-compatible, recommended)
"""

import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    text_blocks: list[str] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Raw content blocks for passthrough (thinking, redacted_thinking, etc.)
    extra_blocks: list[dict] = field(default_factory=list)


class LLMBackend:
    """Abstract base for LLM backends."""

    def __init__(self, model: str, max_tokens: int):
        self.model = model
        self.max_tokens = max_tokens
        self.client = None

    def convert_tools(self, tools: list[dict]) -> list:
        """Convert internal tool definitions to provider-specific format."""
        raise NotImplementedError

    def convert_messages(self, messages: list[dict], system_prompt: str) -> list:
        """Convert internal messages to provider-specific format."""
        raise NotImplementedError

    def create_message(self, system_prompt: str, messages: list[dict],
                       tools: list[dict]) -> LLMResponse:
        """Send a request and return standardized response."""
        raise NotImplementedError

    def stream_message(self, system_prompt: str, messages: list[dict],
                       tools: list[dict]):
        """Stream a request, yielding events as they arrive.

        Yields dicts:
            {"type": "text_delta", "text": "..."}     — text token
            {"type": "tool_call", "tool": ToolCall}   — complete tool call
            {"type": "thinking_delta", "text": "..."}  — thinking content
            {"type": "done", "usage": {...}}           — stream complete
        """
        raise NotImplementedError


class AnthropicBackend(LLMBackend):
    """Anthropic Claude backend (also works with DeepSeek's Anthropic-compatible endpoint)."""

    def __init__(self, model: str, max_tokens: int, api_key: str, base_url: Optional[str] = None):
        super().__init__(model, max_tokens)
        import anthropic
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = anthropic.Anthropic(**kwargs)

    def convert_tools(self, tools: list[dict]) -> list:
        # Already in Anthropic format — pass through
        return tools

    def convert_messages(self, messages: list[dict], system_prompt: str) -> list:
        # Already in Anthropic format — pass through
        return messages

    def create_message(self, system_prompt: str, messages: list[dict],
                       tools: list[dict]) -> LLMResponse:
        response = self.client.messages.create(
            model=self.model,
            system=system_prompt,
            messages=messages,
            tools=tools if tools else None,
            max_tokens=self.max_tokens,
        )
        result = LLMResponse()
        content = getattr(response, 'content', None)
        if content is None:
            return result  # Return empty response — caller handles gracefully
        for block in content:
            if block.type == "text":
                result.text_blocks.append(block.text)
            elif block.type == "tool_use":
                result.tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    input=block.input if isinstance(block.input, dict) else {},
                ))
            elif block.type in ("thinking", "redacted_thinking"):
                # Must be passed back to API in subsequent requests
                result.extra_blocks.append({
                    "type": block.type,
                    "thinking": getattr(block, "thinking", ""),
                    "signature": getattr(block, "signature", ""),
                    "data": getattr(block, "data", None),
                })
        return result

    def stream_message(self, system_prompt: str, messages: list[dict],
                       tools: list[dict]):
        """Stream Anthropic response, yielding text/tool/thinking events."""
        tool_input_accumulators: dict[int, str] = {}
        tool_name_accumulators: dict[int, str] = {}
        tool_id_accumulators: dict[int, str] = {}
        usage_info = {}

        with self.client.messages.stream(
            model=self.model,
            system=system_prompt,
            messages=messages,
            tools=tools if tools else None,
            max_tokens=self.max_tokens,
        ) as stream:
            for event in stream:
                if event.type == "content_block_start":
                    idx = event.index
                    if event.content_block.type == "tool_use":
                        tool_name_accumulators[idx] = event.content_block.name
                        tool_id_accumulators[idx] = event.content_block.id
                        tool_input_accumulators[idx] = ""

                elif event.type == "content_block_delta":
                    idx = event.index
                    if event.delta.type == "text_delta":
                        yield {"type": "text_delta", "text": event.delta.text}
                    elif event.delta.type == "input_json_delta":
                        tool_input_accumulators[idx] = (
                            tool_input_accumulators.get(idx, "") + event.delta.partial_json
                        )
                    elif event.delta.type == "thinking_delta":
                        yield {"type": "thinking_delta", "text": event.delta.thinking}
                    elif event.delta.type == "signature_delta":
                        pass  # signature is internal

                elif event.type == "content_block_stop":
                    idx = event.index
                    if idx in tool_input_accumulators:
                        try:
                            tool_input = json.loads(tool_input_accumulators[idx])
                        except json.JSONDecodeError:
                            tool_input = {}
                        yield {
                            "type": "tool_call",
                            "tool": ToolCall(
                                id=tool_id_accumulators.get(idx, ""),
                                name=tool_name_accumulators.get(idx, ""),
                                input=tool_input,
                            ),
                        }
                        del tool_input_accumulators[idx]
                        del tool_name_accumulators[idx]
                        del tool_id_accumulators[idx]

                elif event.type == "message_delta":
                    usage_info = {
                        "stop_reason": getattr(event.delta, "stop_reason", None),
                        "stop_sequence": getattr(event.delta, "stop_sequence", None),
                        "output_tokens": getattr(event.usage, "output_tokens", 0),
                    }

        yield {"type": "done", "usage": usage_info}


class OpenAICompatibleBackend(LLMBackend):
    """OpenAI / DeepSeek compatible backend."""

    def __init__(self, model: str, max_tokens: int, api_key: str, base_url: Optional[str] = None):
        super().__init__(model, max_tokens)
        import openai
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = openai.OpenAI(**kwargs)

    def _tool_to_openai(self, tool: dict) -> dict:
        """Convert one Anthropic-format tool to OpenAI format."""
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        }

    def convert_tools(self, tools: list[dict]) -> list:
        return [self._tool_to_openai(t) for t in tools]

    def convert_messages(self, messages: list[dict], system_prompt: str) -> list:
        """Convert internal Anthropic-format messages to OpenAI format."""
        openai_msgs = []

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if role == "user":
                # User content is always a string in our internal format
                openai_msgs.append({"role": "user", "content": str(content)})

            elif role == "assistant":
                # Content is a list of blocks
                text_parts = []
                tool_calls = []
                tool_results = []

                for block in content:
                    if block["type"] == "text":
                        text_parts.append(block["text"])
                    elif block["type"] == "tool_use":
                        tool_calls.append({
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block["input"]),
                            },
                        })
                    elif block["type"] == "tool_result":
                        tool_results.append({
                            "tool_call_id": block["tool_use_id"],
                            "role": "tool",
                            "content": str(block["content"]),
                        })

                # OpenAI: assistant message with optional tool_calls
                if text_parts or tool_calls:
                    assistant_msg = {"role": "assistant", "content": "\n".join(text_parts) if text_parts else None}
                    if tool_calls:
                        assistant_msg["tool_calls"] = tool_calls
                    if assistant_msg["content"] is None and not tool_calls:
                        assistant_msg["content"] = ""
                    openai_msgs.append(assistant_msg)

                # OpenAI: separate tool result messages
                for tr in tool_results:
                    openai_msgs.append(tr)

        return openai_msgs

    def create_message(self, system_prompt: str, messages: list[dict],
                       tools: list[dict]) -> LLMResponse:
        # Build the full message list with system prompt
        api_messages = [{"role": "system", "content": system_prompt}]
        api_messages.extend(self.convert_messages(messages, system_prompt))

        kwargs = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": self.max_tokens,
        }
        openai_tools = self.convert_tools(tools)
        if openai_tools:
            kwargs["tools"] = openai_tools

        response = self.client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        result = LLMResponse()
        if msg.content:
            result.text_blocks.append(msg.content)
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    tool_input = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, AttributeError):
                    tool_input = {}
                result.tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    input=tool_input,
                ))
        return result

    def stream_message(self, system_prompt: str, messages: list[dict],
                       tools: list[dict]):
        """Stream OpenAI-compatible response, yielding text/tool events."""
        api_messages = [{"role": "system", "content": system_prompt}]
        api_messages.extend(self.convert_messages(messages, system_prompt))

        kwargs = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        openai_tools = self.convert_tools(tools)
        if openai_tools:
            kwargs["tools"] = openai_tools

        response = self.client.chat.completions.create(**kwargs)

        tool_acc: dict[int, dict] = {}  # idx -> {id, name, arguments_str}
        usage_info = {}

        for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # Text delta
            if delta.content:
                yield {"type": "text_delta", "text": delta.content}

            # Tool call deltas (accumulated by index)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_acc:
                        tool_acc[idx] = {"id": "", "name": "", "arguments_str": ""}
                    if tc.id:
                        tool_acc[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_acc[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_acc[idx]["arguments_str"] += tc.function.arguments

            # Check for finish_reason — tool calls are now complete
            finish_reason = chunk.choices[0].finish_reason if chunk.choices else None
            if finish_reason == "tool_calls":
                for idx in sorted(tool_acc.keys()):
                    entry = tool_acc[idx]
                    try:
                        tool_input = json.loads(entry["arguments_str"])
                    except (json.JSONDecodeError, AttributeError):
                        tool_input = {}
                    yield {
                        "type": "tool_call",
                        "tool": ToolCall(
                            id=entry["id"],
                            name=entry["name"],
                            input=tool_input,
                        ),
                    }
                tool_acc.clear()

            # Usage info at stream end
            if chunk.usage:
                usage_info = {
                    "input_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                    "output_tokens": getattr(chunk.usage, "completion_tokens", 0),
                }

        yield {"type": "done", "usage": usage_info}


def create_backend(config: dict) -> LLMBackend:
    """Factory: create the appropriate LLM backend from config."""
    import os

    llm_cfg = config.get("llm", {})
    provider = llm_cfg.get("provider", "anthropic").lower()
    model = llm_cfg.get("model", "claude-sonnet-4-6-20250514")
    max_tokens = llm_cfg.get("max_tokens", 8192)
    api_key_env = llm_cfg.get("api_key_env", "ANTHROPIC_API_KEY")
    base_url = llm_cfg.get("base_url")

    api_key = os.environ.get(api_key_env, "")

    if provider in ("openai", "deepseek"):
        return OpenAICompatibleBackend(
            model=model,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=base_url,
        )
    else:
        return AnthropicBackend(
            model=model,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=base_url,
        )
