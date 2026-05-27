"""
LLM Call Logger — structured JSONL logging of LLM interactions.

Logs every LLM request/response and tool execution for debugging,
cost tracking, and observability.

Stored per-agent at agent_workspace/<name>/logs/llm_calls.jsonl
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class LLMLogger:
    """Structured logger for LLM and tool-execution events.

    Usage:
        logger = LLMLogger(Path("agent_workspace/my_agent/logs"))
        logger.log_request(provider="minimax", model="MiniMax-M2.7", ...)
        logger.log_response(...)
        logger.log_tool_result(...)
    """

    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / "llm_calls.jsonl"

    # ── Request ────────────────────────────────────────────────────

    def log_request(self, provider: str, model: str, messages_count: int,
                    estimated_tokens: int, tools: Optional[list] = None,
                    request_id: str = "") -> str:
        """Log an LLM request. Returns the request_id for correlating response."""
        req_id = request_id or _make_id()
        entry = {
            "type": "request",
            "request_id": req_id,
            "timestamp": _now_iso(),
            "provider": provider,
            "model": model,
            "messages_count": messages_count,
            "estimated_tokens": estimated_tokens,
            "tool_names": [t.get("name", "") for t in (tools or [])],
        }
        self._write(entry)
        return req_id

    # ── Response ───────────────────────────────────────────────────

    def log_response(self, request_id: str, finish_reason: str = "",
                     content_preview: str = "", thinking_preview: str = "",
                     tool_calls_count: int = 0, token_usage: Optional[dict] = None,
                     latency_ms: float = 0, error: Optional[str] = None):
        """Log an LLM response."""
        entry = {
            "type": "response",
            "request_id": request_id,
            "timestamp": _now_iso(),
            "finish_reason": finish_reason,
            "content_preview": _truncate(content_preview, 500),
            "thinking_preview": _truncate(thinking_preview, 500),
            "tool_calls_count": tool_calls_count,
            "input_tokens": token_usage.get("input_tokens", 0) if token_usage else 0,
            "output_tokens": token_usage.get("output_tokens", 0) if token_usage else 0,
            "latency_ms": round(latency_ms, 1),
        }
        if error:
            entry["error"] = error
        self._write(entry)

    # ── Tool result ────────────────────────────────────────────────

    def log_tool_result(self, request_id: str, tool_name: str,
                        arguments: dict, success: bool,
                        result_preview: str, latency_ms: float = 0):
        """Log a tool execution result."""
        entry = {
            "type": "tool_result",
            "request_id": request_id,
            "timestamp": _now_iso(),
            "tool_name": tool_name,
            "arguments_preview": _truncate(json.dumps(arguments, ensure_ascii=False), 300),
            "success": success,
            "result_preview": _truncate(result_preview, 1000),
            "latency_ms": round(latency_ms, 1),
        }
        self._write(entry)

    # ── Internal ───────────────────────────────────────────────────

    def _write(self, entry: dict) -> None:
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except IOError:
            pass  # don't break main flow over logging failures


def _make_id() -> str:
    import uuid
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."
