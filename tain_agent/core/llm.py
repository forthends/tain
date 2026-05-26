"""
LLM Backend Abstraction — 多模型支持

Supports:
- Anthropic (Claude)
- OpenAI
- DeepSeek (OpenAI-compatible)
- MiniMax (Anthropic-compatible, recommended)
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from tain_agent.core.retry import RetryConfig, retry_call, retry_stream
from tain_agent.core.llm_logger import LLMLogger

logger = logging.getLogger(__name__)


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

    def __init__(self, model: str, max_tokens: int, retry_config: Optional[RetryConfig] = None):
        self.model = model
        self.max_tokens = max_tokens
        self.client = None
        self.retry_config = retry_config or RetryConfig(enabled=False)
        self.logger: Optional[LLMLogger] = None

    def set_logger(self, logger: LLMLogger) -> None:
        self.logger = logger

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
    """Anthropic Claude backend (also works with DeepSeek and MiniMax via their Anthropic-compatible endpoints)."""

    def __init__(self, model: str, max_tokens: int, api_key: str,
                 base_url: Optional[str] = None, retry_config: Optional[RetryConfig] = None,
                 provider: str = "anthropic"):
        super().__init__(model, max_tokens, retry_config)
        self.provider = provider
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
        import time as _time

        # Estimate tokens for logging
        estimated = 0
        try:
            from tain_agent.core.conversation import ConversationManager
            estimated = ConversationManager._count_tokens(
                ConversationManager._messages_to_text(messages)
            )
        except Exception:
            pass

        request_id = self.logger.log_request(
            provider=self.provider, model=self.model,
            messages_count=len(messages), estimated_tokens=estimated,
            tools=tools,
        ) if self.logger else ""

        t0 = _time.monotonic()

        def _call():
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
                return result
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
                    result.extra_blocks.append({
                        "type": block.type,
                        "thinking": getattr(block, "thinking", ""),
                        "signature": getattr(block, "signature", ""),
                        "data": getattr(block, "data", None),
                    })
            return result

        try:
            result = retry_call(self.retry_config, _call)
            if self.logger:
                latency_ms = (_time.monotonic() - t0) * 1000
                self.logger.log_response(
                    request_id=request_id,
                    finish_reason="stop",
                    content_preview="\n".join(result.text_blocks),
                    tool_calls_count=len(result.tool_calls),
                    latency_ms=latency_ms,
                )
            return result
        except Exception as exc:
            if self.logger:
                latency_ms = (_time.monotonic() - t0) * 1000
                self.logger.log_response(
                    request_id=request_id, error=str(exc), latency_ms=latency_ms,
                )
            raise

    def stream_message(self, system_prompt: str, messages: list[dict],
                       tools: list[dict]):
        """Stream Anthropic response, yielding text/tool/thinking events."""
        import time as _time

        tool_input_accumulators: dict[int, str] = {}
        tool_name_accumulators: dict[int, str] = {}
        tool_id_accumulators: dict[int, str] = {}
        usage_info = {}
        content_parts: list[str] = []

        estimated = 0
        try:
            from tain_agent.core.conversation import ConversationManager
            estimated = ConversationManager._count_tokens(
                ConversationManager._messages_to_text(messages)
            )
        except Exception:
            pass

        request_id = self.logger.log_request(
            provider=self.provider, model=self.model,
            messages_count=len(messages), estimated_tokens=estimated,
            tools=tools,
        ) if self.logger else ""

        t0 = _time.monotonic()

        def _create_and_yield():
            nonlocal usage_info
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
                            content_parts.append(event.delta.text)
                            yield {"type": "text_delta", "text": event.delta.text}
                        elif event.delta.type == "input_json_delta":
                            tool_input_accumulators[idx] = (
                                tool_input_accumulators.get(idx, "") + event.delta.partial_json
                            )
                        elif event.delta.type == "thinking_delta":
                            yield {"type": "thinking_delta", "text": event.delta.thinking}
                        elif event.delta.type == "signature_delta":
                            pass

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

        try:
            yield from retry_stream(self.retry_config, _create_and_yield)
        except Exception as exc:
            if self.logger:
                self.logger.log_response(
                    request_id=request_id, error=str(exc),
                    latency_ms=(_time.monotonic() - t0) * 1000,
                )
            raise

        if self.logger:
            self.logger.log_response(
                request_id=request_id,
                finish_reason=usage_info.get("stop_reason", ""),
                content_preview="".join(content_parts),
                tool_calls_count=len(tool_input_accumulators),
                token_usage=usage_info,
                latency_ms=(_time.monotonic() - t0) * 1000,
            )

        yield {"type": "done", "usage": usage_info}


class OpenAICompatibleBackend(LLMBackend):
    """OpenAI / DeepSeek compatible backend."""

    def __init__(self, model: str, max_tokens: int, api_key: str,
                 base_url: Optional[str] = None, retry_config: Optional[RetryConfig] = None):
        super().__init__(model, max_tokens, retry_config)
        import openai
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = openai.OpenAI(**kwargs)

    _VALID_JSON_TYPES = {"string", "number", "integer", "boolean", "array", "object", "null"}

    @classmethod
    def _sanitize_schema(cls, schema: dict) -> dict:
        """Recursively fix invalid JSON Schema types (e.g. Python 'Any' → 'string')."""
        if not isinstance(schema, dict):
            return schema
        result = {}
        for key, value in schema.items():
            if key == "type" and isinstance(value, str) and value not in cls._VALID_JSON_TYPES:
                # Map Python-like type hints to valid JSON Schema types
                if value.startswith("List") or value.startswith("list"):
                    result[key] = "array"
                elif value.startswith("Dict") or value.startswith("dict"):
                    result[key] = "object"
                else:
                    result[key] = "string"
            elif key == "properties" and isinstance(value, dict):
                result[key] = {k: cls._sanitize_schema(v) for k, v in value.items()}
            elif key == "items" and isinstance(value, dict):
                result[key] = cls._sanitize_schema(value)
            elif key in ("anyOf", "oneOf", "allOf") and isinstance(value, list):
                result[key] = [cls._sanitize_schema(item) for item in value]
            else:
                result[key] = value
        return result

    def _tool_to_openai(self, tool: dict) -> dict:
        """Convert one Anthropic-format tool to OpenAI format."""
        schema = tool.get("input_schema", {"type": "object", "properties": {}})
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": self._sanitize_schema(schema),
            },
        }

    def convert_tools(self, tools: list[dict]) -> list:
        if not tools:
            return []
        return [self._tool_to_openai(t) for t in tools]

    def convert_messages(self, messages: list[dict], system_prompt: str) -> list:
        """Convert internal Anthropic-format messages to OpenAI format."""
        openai_msgs = []

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if role == "user":
                # Content may be a string or a list of tool_result blocks
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            openai_msgs.append({
                                "role": "tool",
                                "tool_call_id": block.get("tool_use_id", ""),
                                "content": str(block.get("content", "")),
                            })
                        else:
                            openai_msgs.append({"role": "user", "content": str(block)})
                else:
                    openai_msgs.append({"role": "user", "content": str(content)})

            elif role == "assistant":
                # Content may be a plain string (from chat history) or a list of blocks
                if isinstance(content, str):
                    assistant_msg = {"role": "assistant", "content": content}
                    if msg.get("reasoning_content"):
                        assistant_msg["reasoning_content"] = msg["reasoning_content"]
                    openai_msgs.append(assistant_msg)
                    continue

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
                    if assistant_msg["content"] is None:
                        assistant_msg["content"] = ""
                    if msg.get("reasoning_content"):
                        assistant_msg["reasoning_content"] = msg["reasoning_content"]
                    openai_msgs.append(assistant_msg)

                # OpenAI: separate tool result messages
                for tr in tool_results:
                    openai_msgs.append(tr)

        return openai_msgs

    def create_message(self, system_prompt: str, messages: list[dict],
                       tools: list[dict]) -> LLMResponse:
        import time as _time

        estimated = 0
        try:
            from tain_agent.core.conversation import ConversationManager
            estimated = ConversationManager._count_tokens(
                ConversationManager._messages_to_text(messages)
            )
        except Exception:
            pass

        request_id = self.logger.log_request(
            provider="openai", model=self.model,
            messages_count=len(messages), estimated_tokens=estimated,
            tools=tools,
        ) if self.logger else ""

        t0 = _time.monotonic()

        def _call():
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

        try:
            result = retry_call(self.retry_config, _call)
            if self.logger:
                latency_ms = (_time.monotonic() - t0) * 1000
                self.logger.log_response(
                    request_id=request_id,
                    finish_reason="stop",
                    content_preview="\n".join(result.text_blocks),
                    tool_calls_count=len(result.tool_calls),
                    latency_ms=latency_ms,
                )
            return result
        except Exception as exc:
            if self.logger:
                latency_ms = (_time.monotonic() - t0) * 1000
                self.logger.log_response(
                    request_id=request_id, error=str(exc), latency_ms=latency_ms,
                )
            raise

    def stream_message(self, system_prompt: str, messages: list[dict],
                       tools: list[dict]):
        """Stream OpenAI-compatible response, yielding text/tool events."""
        import time as _time

        tool_acc: dict[int, dict] = {}
        reasoning_parts: list[str] = []
        content_parts: list[str] = []
        usage_info = {}

        estimated = 0
        try:
            from tain_agent.core.conversation import ConversationManager
            estimated = ConversationManager._count_tokens(
                ConversationManager._messages_to_text(messages)
            )
        except Exception:
            pass

        request_id = self.logger.log_request(
            provider="openai", model=self.model,
            messages_count=len(messages), estimated_tokens=estimated,
            tools=tools,
        ) if self.logger else ""

        t0 = _time.monotonic()

        def _create_and_yield():
            nonlocal usage_info
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

            for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                reasoning = getattr(delta, 'reasoning_content', None) or getattr(delta, 'thinking', None)
                if reasoning:
                    reasoning_parts.append(reasoning)
                    yield {"type": "thinking_delta", "text": reasoning}

                if delta.content:
                    content_parts.append(delta.content)
                    yield {"type": "text_delta", "text": delta.content}

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

                if chunk.usage:
                    usage_info = {
                        "input_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                        "output_tokens": getattr(chunk.usage, "completion_tokens", 0),
                    }

        try:
            yield from retry_stream(self.retry_config, _create_and_yield)
        except Exception as exc:
            if self.logger:
                self.logger.log_response(
                    request_id=request_id, error=str(exc),
                    latency_ms=(_time.monotonic() - t0) * 1000,
                )
            raise

        if self.logger:
            self.logger.log_response(
                request_id=request_id,
                finish_reason=usage_info.get("stop_reason", "tool_calls"),
                content_preview="".join(content_parts),
                thinking_preview="".join(reasoning_parts),
                tool_calls_count=len(tool_acc),
                token_usage=usage_info,
                latency_ms=(_time.monotonic() - t0) * 1000,
            )

        yield {"type": "done", "usage": usage_info, "reasoning_content": "".join(reasoning_parts)}


def create_backend(config: dict) -> LLMBackend:
    """Factory: create the appropriate LLM backend from config."""
    import os

    llm_cfg = config.get("llm", {})
    provider = llm_cfg.get("provider", "minimax").lower()
    model = llm_cfg.get("model", "MiniMax-M2.7")
    max_tokens = llm_cfg.get("max_tokens", 8192)
    api_key_env = llm_cfg.get("api_key_env", "MINIMAX_API_KEY")
    base_url = llm_cfg.get("base_url")

    api_key = os.environ.get(api_key_env, "")

    retry_config = RetryConfig.from_config(llm_cfg)

    # Anthropic-compatible endpoint (MiniMax, DeepSeek, etc. via /anthropic)
    if base_url and "/anthropic" in base_url:
        return AnthropicBackend(
            model=model,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=base_url,
            retry_config=retry_config,
            provider=provider,
        )

    if provider in ("openai", "deepseek"):
        return OpenAICompatibleBackend(
            model=model,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=base_url,
            retry_config=retry_config,
        )
    else:
        return AnthropicBackend(
            model=model,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=base_url,
            retry_config=retry_config,
        )
