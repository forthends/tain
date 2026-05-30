"""Tests for tain_agent.tools.templates"""

import tempfile
from pathlib import Path
from tain_agent.tools.templates import (
    resolve_path, truncate_output, truncate_lines,
    run_shell, format_error, estimate_tokens,
)


class TestResolvePath:
    def test_relative_path(self):
        with tempfile.TemporaryDirectory() as d:
            result = resolve_path(d, "subdir/file.txt")
            assert result is not None
            assert str(result).endswith("subdir/file.txt")

    def test_path_within_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            ws = Path(d)
            abs_path = ws / "data" / "file.txt"
            abs_path.parent.mkdir()
            abs_path.touch()
            result = resolve_path(d, str(abs_path))
            assert result is not None

    def test_path_escape_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            result = resolve_path(d, "/etc/passwd")
            assert result is None

    def test_nonexistent_path_resolved(self):
        with tempfile.TemporaryDirectory() as d:
            result = resolve_path(d, "new/file.txt")
            assert result is not None
            # On macOS /var is a symlink to /private/var, so use Path.resolve()
            resolved_d = str(Path(d).resolve())
            assert str(result).startswith(resolved_d) or str(Path(str(result)).resolve()).startswith(resolved_d)


class TestTruncateOutput:
    def test_no_truncation(self):
        result = truncate_output("short text", max_tokens=100)
        assert result == "short text"

    def test_truncation_applied(self):
        long_text = "A" * 10000
        result = truncate_output(long_text, max_tokens=50)
        assert len(result) < len(long_text)
        assert "truncated" in result.lower()

    def test_head_and_tail_preserved(self):
        text = "START " + "x" * 10000 + " END"
        result = truncate_output(text, max_tokens=50)
        assert result.startswith("START")
        assert result.rstrip().endswith("END")


class TestTruncateLines:
    def test_no_truncation(self):
        text = "line1\nline2\nline3"
        result = truncate_lines(text, max_lines=10)
        assert result == text

    def test_truncation(self):
        text = "\n".join(f"line {i}" for i in range(100))
        result = truncate_lines(text, max_lines=20)
        assert len(result.split("\n")) < 100
        assert "truncated" in result


class TestRunShell:
    def test_echo(self):
        result = run_shell("echo hello")
        assert result["success"] is True
        assert "hello" in result["stdout"]

    def test_failing_command(self):
        result = run_shell("exit 1")
        assert result["success"] is False
        assert result["exit_code"] == 1

    def test_timeout(self):
        result = run_shell("sleep 5", timeout=0.1)
        assert result["success"] is False
        assert "timed out" in result["stderr"].lower()


class TestFormatError:
    def test_basic(self):
        result = format_error("Something went wrong")
        assert result["success"] is False
        assert result["error"] == "Something went wrong"
        assert result["error_type"] == "tool_error"

    def test_with_exception(self):
        try:
            raise ValueError("test error")
        except ValueError as e:
            result = format_error("Failed", e)
        assert "ValueError" in result["exception"]
        assert "traceback" in result

    def test_without_exception(self):
        result = format_error("just a message")
        assert "traceback" not in result


class TestEstimateTokens:
    def test_short_text(self):
        est = estimate_tokens("hello")
        assert est > 0

    def test_longer_text(self):
        text = "Hello " * 801  # 4005 chars × 2/5 ≈ 1602 → > 400
        est = estimate_tokens(text)
        assert est > 400

    def test_chinese_text(self):
        est = estimate_tokens("你好世界 " * 100)
        assert est > 0
