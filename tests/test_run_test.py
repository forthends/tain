"""Tests for run_test tool."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestRunTestFunctionMode:
    """Test function mode — import and call main()."""

    def test_calls_main_and_returns_result(self):
        """Function mode should import the tool module and call its main()."""
        code = "def main():\n    return 'hello'"
        from tain_agent.tools.primal import run_test
        with patch("tain_agent.tools.primal._WORKSPACE_DIR", Path("/tmp/test_ws")):
            result = run_test(
                test_target="my_tool",
                test_type="function",
                test_code=code,
            )
        assert result["passed"] is True
        assert "hello" in str(result.get("output", ""))

    def test_function_with_exception_returns_failed(self):
        """Function that raises should return passed=False with error info."""
        code = "def main():\n    raise ValueError('boom')"
        from tain_agent.tools.primal import run_test
        with patch("tain_agent.tools.primal._WORKSPACE_DIR", Path("/tmp/test_ws")):
            result = run_test(
                test_target="bad_tool",
                test_type="function",
                test_code=code,
            )
        assert result["passed"] is False
        assert "ValueError" in str(result.get("errors", ""))
        assert result["total"] == 1
        assert result["failures"] >= 1

    def test_no_main_function_found(self):
        """Code without a main() function should return error."""
        code = "x = 1\ny = [1, 2, 3]\nz = sum(y)"
        from tain_agent.tools.primal import run_test
        with patch("tain_agent.tools.primal._WORKSPACE_DIR", Path("/tmp/test_ws")):
            result = run_test(
                test_target="no_main",
                test_type="function",
                test_code=code,
            )
        assert result["passed"] is False
        assert "main" in str(result.get("errors", "")).lower() or result["failures"] >= 1


class TestRunTestAssertMode:
    """Test assert mode — execute assertion code snippet."""

    def test_assert_passes_returns_true(self):
        """Valid assert should return passed=True."""
        from tain_agent.tools.primal import run_test
        with patch("tain_agent.tools.primal._WORKSPACE_DIR", Path("/tmp/test_ws")):
            result = run_test(
                test_target="assert_test",
                test_type="assert",
                test_code="result = sum([1, 2, 3])\nassert result == 6, f'Expected 6 got {result}'",
            )
        assert result["passed"] is True

    def test_assert_fails_returns_false(self):
        """Failing assert should return passed=False with AssertionError."""
        from tain_agent.tools.primal import run_test
        with patch("tain_agent.tools.primal._WORKSPACE_DIR", Path("/tmp/test_ws")):
            result = run_test(
                test_target="fail_assert",
                test_type="assert",
                test_code="assert 1 == 2, 'one does not equal two'",
            )
        assert result["passed"] is False
        assert "one does not equal two" in str(result.get("errors", ""))


class TestRunTestTimeout:
    """Test timeout handling."""

    def test_function_exceeding_timeout(self):
        """Function that runs too long should be terminated."""
        code = "import time\ndef main():\n    time.sleep(5)\n    return 'done'"
        from tain_agent.tools.primal import run_test
        with patch("tain_agent.tools.primal._WORKSPACE_DIR", Path("/tmp/test_ws")):
            result = run_test(
                test_target="slow_tool",
                test_type="function",
                test_code=code,
                timeout=1,
            )
        assert result["passed"] is False
        assert "timeout" in str(result.get("errors", "")).lower()
