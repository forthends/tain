"""Tests for ForgeCycle."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tain_agent.evolution.forge_cycle import ForgeCycle, ForgeResult


class TestForgeCycleRun:
    """Test the full five-stage forge cycle."""

    def _make_forge_cycle(self, **overrides):
        """Build a ForgeCycle with mock dependencies."""
        defaults = {
            "tool_forge": MagicMock(),
            "dependency_manager": MagicMock(),
            "capability_registry": MagicMock(),
            "decision_log": MagicMock(),
            "lineage_tracker": MagicMock(),
            "memory": MagicMock(),
            "llm_backend": MagicMock(),
        }
        defaults.update(overrides)
        fc = ForgeCycle(**defaults)
        return fc

    def test_full_cycle_success(self):
        """All five stages pass — tool should be registered."""
        fc = self._make_forge_cycle()

        fc._generate_code = MagicMock(return_value={
            "code": "def main():\n    return 'ok'",
            "dependencies": ["requests"],
            "test_code": "assert True",
            "tool_name": "test_tool",
            "description": "A test tool",
            "parameters": {},
        })

        fc._tool_forge.forge.return_value = {"success": True}

        dep_result = MagicMock()
        dep_result.installed = ["requests"]
        dep_result.rejected = []
        dep_result.applications = []
        fc._dependency_manager.resolve.return_value = dep_result

        fc._run_test_in_sandbox = MagicMock(return_value={
            "passed": True, "total": 1, "failures": 0, "errors": "", "output": "ok",
        })

        gap_spec = {"capability_id": "test.capability", "description": "Need a test capability"}
        result = fc.run(gap_spec)

        assert result.success is True
        assert result.registered is True
        assert result.stage_results["generate"]["passed"] is True
        assert result.stage_results["forge"]["passed"] is True
        assert result.stage_results["install"]["passed"] is True
        assert result.stage_results["test"]["passed"] is True
        assert result.stage_results["register"]["passed"] is True
        fc._capability_registry.record_improvement.assert_called_once()

    def test_generate_stage_failure_stops_pipeline(self):
        """LLM generation failure should stop the pipeline at stage 1."""
        fc = self._make_forge_cycle()
        fc._generate_code = MagicMock(return_value={"error": "LLM unavailable"})

        result = fc.run({"capability_id": "x", "description": "y"})
        assert result.success is False
        assert result.stage_results["generate"]["passed"] is False
        fc._tool_forge.forge.assert_not_called()

    def test_forge_stage_failure_stops_pipeline(self):
        """ToolSandbox rejection should stop at stage 2."""
        fc = self._make_forge_cycle()
        fc._generate_code = MagicMock(return_value={
            "code": "def main():\n    return 'ok'",
            "dependencies": [],
            "test_code": "",
            "tool_name": "blocked_tool",
            "description": "Will be blocked",
            "parameters": {},
        })
        fc._tool_forge.forge.return_value = {
            "success": False,
            "error": "ToolSandbox rejected: blocked_import 'os'",
        }

        result = fc.run({"capability_id": "x", "description": "y"})
        assert result.success is False
        assert result.registered is False
        assert result.stage_results["forge"]["passed"] is False
        fc._capability_registry.record_improvement.assert_not_called()

    def test_test_stage_failure_no_register(self):
        """Test failure should prevent registration."""
        fc = self._make_forge_cycle()
        fc._generate_code = MagicMock(return_value={
            "code": "def main():\n    return 'bad'",
            "dependencies": [],
            "test_code": "assert False",
            "tool_name": "buggy_tool",
            "description": "Has bugs",
            "parameters": {},
        })
        fc._tool_forge.forge.return_value = {"success": True}
        dep_result = MagicMock()
        dep_result.installed = []
        dep_result.rejected = []
        dep_result.applications = []
        fc._dependency_manager.resolve.return_value = dep_result
        fc._run_test_in_sandbox = MagicMock(return_value={
            "passed": False, "total": 1, "failures": 1,
            "errors": "AssertionError: ", "output": "",
        })

        result = fc.run({"capability_id": "x", "description": "y"})
        assert result.success is False
        assert result.registered is False
        fc._capability_registry.record_improvement.assert_not_called()

    def test_quota_exceeded_rejects(self):
        """After MAX_FORGES_PER_SESSION, run() should reject."""
        fc = self._make_forge_cycle()
        fc._forge_count = fc._max_forges

        result = fc.run({"capability_id": "x", "description": "y"})
        assert result.success is False
        assert "quota" in result.summary.lower()

    def test_quota_respected_across_runs(self):
        """Run should increment counter and honor limit."""
        fc = self._make_forge_cycle()
        fc._generate_code = MagicMock(return_value={
            "code": "def main():\n    return 'ok'",
            "dependencies": [], "test_code": "",
            "tool_name": "tool_{}", "description": "desc", "parameters": {},
        })
        fc._tool_forge.forge.return_value = {"success": True}
        dep_result = MagicMock()
        dep_result.installed = []
        dep_result.rejected = []
        dep_result.applications = []
        fc._dependency_manager.resolve.return_value = dep_result
        fc._run_test_in_sandbox = MagicMock(return_value={
            "passed": True, "total": 1, "failures": 0, "errors": "", "output": "ok",
        })

        for i in range(3):
            fc._generate_code.return_value["tool_name"] = f"tool_{i}"
            result = fc.run({"capability_id": f"x_{i}", "description": f"desc_{i}"})
            assert result.success is True, f"Cycle {i} should succeed"

        fc._generate_code.return_value["tool_name"] = "tool_4"
        result = fc.run({"capability_id": "x_4", "description": "desc_4"})
        assert result.success is False
        assert "quota" in result.summary.lower()
