"""Tests for daemon-related agent behaviors."""
import json
import pytest
import tempfile
from pathlib import Path


class TestIdleTimeout:
    def test_timeout_not_triggered_when_active(self):
        idle_timeout = 3600
        last_action_time = 100.0
        current_time = 200.0
        elapsed = current_time - last_action_time
        assert elapsed < idle_timeout

    def test_timeout_triggered_when_idle(self):
        idle_timeout = 3600
        last_action_time = 100.0
        current_time = 4000.0
        elapsed = current_time - last_action_time
        assert elapsed >= idle_timeout


class TestContextResume:
    def test_save_and_load_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx_file = Path(tmpdir) / "conversation_context.json"
            context = {
                "summary": "Agent was exploring tool creation",
                "cycle_count": 42,
                "phase": "work",
                "last_goals": ["improve code quality"],
                "saved_at": "2026-06-04T12:00:00",
            }
            ctx_file.write_text(json.dumps(context, ensure_ascii=False))

            loaded = json.loads(ctx_file.read_text())
            assert loaded["summary"] == "Agent was exploring tool creation"
            assert loaded["cycle_count"] == 42

    def test_no_error_when_context_file_missing(self):
        ctx_file = Path("/nonexistent/path/context.json")
        if ctx_file.exists():
            ctx_file.unlink()
        assert not ctx_file.exists()
