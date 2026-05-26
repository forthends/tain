"""Tests for tain_agent.core.llm_logger"""

import json
import tempfile
from pathlib import Path
from tain_agent.core.llm_logger import LLMLogger, _truncate


class TestLLMLogger:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.tmp.name)
        self.logger = LLMLogger(self.log_dir)

    def teardown_method(self):
        self.tmp.cleanup()

    def test_log_request_creates_file(self):
        req_id = self.logger.log_request(
            provider="minimax", model="M2.7",
            messages_count=5, estimated_tokens=1200,
            tools=[{"name": "search"}],
        )
        assert req_id
        entries = self._read_log()
        assert len(entries) == 1
        assert entries[0]["type"] == "request"
        assert entries[0]["provider"] == "minimax"
        assert entries[0]["model"] == "M2.7"
        assert entries[0]["tool_names"] == ["search"]

    def test_log_response(self):
        req_id = self.logger.log_request(
            provider="anthropic", model="claude",
            messages_count=3, estimated_tokens=500,
        )
        self.logger.log_response(
            request_id=req_id,
            finish_reason="stop",
            content_preview="Hello world",
            tool_calls_count=0,
            latency_ms=1234.5,
        )
        entries = self._read_log()
        assert len(entries) == 2
        resp = entries[1]
        assert resp["type"] == "response"
        assert resp["finish_reason"] == "stop"
        assert resp["latency_ms"] == 1234.5
        assert resp["tool_calls_count"] == 0

    def test_log_response_with_error(self):
        req_id = self.logger.log_request(
            provider="openai", model="gpt-4",
            messages_count=2, estimated_tokens=100,
        )
        self.logger.log_response(
            request_id=req_id,
            error="Connection timeout",
            latency_ms=5000.0,
        )
        entries = self._read_log()
        assert entries[1]["error"] == "Connection timeout"

    def test_log_response_with_token_usage(self):
        req_id = self.logger.log_request(
            provider="minimax", model="M2.7",
            messages_count=10, estimated_tokens=3000,
        )
        self.logger.log_response(
            request_id=req_id,
            token_usage={"input_tokens": 2500, "output_tokens": 300},
            latency_ms=800.0,
        )
        entries = self._read_log()
        assert entries[1]["input_tokens"] == 2500
        assert entries[1]["output_tokens"] == 300

    def test_log_tool_result(self):
        req_id = self.logger.log_request(
            provider="minimax", model="M2.7",
            messages_count=4, estimated_tokens=800,
        )
        self.logger.log_tool_result(
            request_id=req_id,
            tool_name="read_file",
            arguments={"path": "/tmp/test.txt"},
            success=True,
            result_preview="File contents here...",
            latency_ms=150.0,
        )
        entries = self._read_log()
        assert len(entries) == 2
        tool_entry = entries[1]
        assert tool_entry["type"] == "tool_result"
        assert tool_entry["tool_name"] == "read_file"
        assert tool_entry["success"] is True

    def test_content_truncated_in_logs(self):
        req_id = self.logger.log_request(
            provider="minimax", model="M2.7",
            messages_count=1, estimated_tokens=100,
        )
        long_content = "A" * 2000
        self.logger.log_response(
            request_id=req_id, content_preview=long_content,
        )
        entries = self._read_log()
        assert len(entries[1]["content_preview"]) <= 503  # 500 + "..."

    def test_arguments_truncated(self):
        req_id = self.logger.log_request(
            provider="minimax", model="M2.7",
            messages_count=1, estimated_tokens=100,
        )
        self.logger.log_tool_result(
            request_id=req_id,
            tool_name="search",
            arguments={"query": "x" * 1000},
            success=True,
            result_preview="ok",
        )
        entries = self._read_log()
        assert len(entries[1]["arguments_preview"]) <= 303  # 300 + "..."

    def test_multiple_requests(self):
        for i in range(5):
            req_id = self.logger.log_request(
                provider="minimax", model="M2.7",
                messages_count=i + 1, estimated_tokens=100 * (i + 1),
            )
            self.logger.log_response(
                request_id=req_id,
                content_preview=f"Response {i}",
            )
        entries = self._read_log()
        assert len(entries) == 10

    def test_log_dir_created(self):
        new_dir = self.log_dir / "sub" / "nested"
        logger = LLMLogger(new_dir)
        assert new_dir.exists()

    def _read_log(self):
        if not self.logger.log_path.exists():
            return []
        entries = []
        for line in self.logger.log_path.read_text().strip().split("\n"):
            if line.strip():
                entries.append(json.loads(line))
        return entries


class TestTruncate:
    def test_no_truncation_needed(self):
        assert _truncate("hello", 100) == "hello"

    def test_truncation_applied(self):
        result = _truncate("A" * 100, 20)
        assert len(result) <= 20
        assert result.endswith("...")

    def test_empty_string(self):
        assert _truncate("", 10) == ""
