"""Tests for the autonomous evolution loop — BehaviorContract and related types."""

from __future__ import annotations

import pytest

from tain_agent.evolution.behavior_contract import (
    BehaviorContract,
    ContractValidationError,
    ContractComplianceResult,
)

# Warm up the kernel module to avoid circular import when later importing
# from plugins.tool.forge_cycle (plugins/tool/__init__.py references kernel.protocol,
# and kernel/__init__.py references kernel.factories which imports ToolPlugin).
import tain_agent.kernel  # noqa: F401
from tain_agent.plugins.tool.forge_cycle import ImprovementSpec


class TestBehaviorContract:
    """Unit tests for BehaviorContract — contract parsing, validation, and AST compliance."""

    def test_from_generated_parses_valid_contract(self):
        """from_generated() parses a valid contract JSON."""
        contract_json = {
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
            "output_schema": {"type": "object", "properties": {"result": {"type": "string"}}},
            "side_effects": ["none"],
            "max_runtime_ms": 3000,
        }
        contract = BehaviorContract.from_generated("search_tool", contract_json)
        assert contract.tool_name == "search_tool"
        assert contract.side_effects == ["none"]
        assert contract.max_runtime_ms == 3000
        assert contract.input_schema["type"] == "object"
        assert contract.output_schema["type"] == "object"

    def test_from_generated_rejects_invalid_side_effects(self):
        """from_generated() raises ContractValidationError for invalid side_effects."""
        contract_json = {
            "input_schema": {},
            "output_schema": {},
            "side_effects": ["eval_code", "unknown"],
            "max_runtime_ms": 1000,
        }
        with pytest.raises(ContractValidationError, match="Invalid side effects"):
            BehaviorContract.from_generated("bad_tool", contract_json)

    def test_from_generated_defaults_missing_fields(self):
        """from_generated() fills in safe defaults for missing optional fields."""
        contract_json = {}
        contract = BehaviorContract.from_generated("minimal_tool", contract_json)
        assert contract.side_effects == ["none"]
        assert contract.max_runtime_ms == 5000
        assert contract.input_schema == {}
        assert contract.output_schema == {}

    def test_code_compliance_passes_clean_code(self):
        """verify_code_compliance() passes for code using only stdlib."""
        contract = BehaviorContract(
            tool_name="math_tool", input_schema={}, output_schema={},
            side_effects=["none"], max_runtime_ms=1000,
        )
        code = '''"""A simple math tool."""
import json
import math
from collections import defaultdict

def math_tool(x: float) -> dict:
    """Compute square root."""
    return {"result": math.sqrt(x)}
'''
        result = contract.verify_code_compliance(code)
        assert result.compliant is True
        assert len(result.violations) == 0

    def test_code_compliance_detects_network_violation(self):
        """verify_code_compliance() flags import urllib when side_effects=['none']."""
        contract = BehaviorContract(
            tool_name="sneaky_tool", input_schema={}, output_schema={},
            side_effects=["none"], max_runtime_ms=1000,
        )
        code = '''"""Sneaky tool that imports network."""
import urllib.parse

def sneaky_tool(url: str) -> dict:
    return {"parsed": urllib.parse.urlparse(url)}
'''
        result = contract.verify_code_compliance(code)
        assert result.compliant is False
        assert len(result.violations) > 0
        assert any("urllib" in v for v in result.violations)

    def test_code_compliance_allows_declared_network(self):
        """verify_code_compliance() passes when side_effects match declared imports."""
        contract = BehaviorContract(
            tool_name="web_tool", input_schema={}, output_schema={},
            side_effects=["network"], max_runtime_ms=2000,
        )
        code = '''"""A web tool."""
import urllib.request
import json

def web_tool() -> dict:
    return {"status": "ok"}
'''
        result = contract.verify_code_compliance(code)
        assert result.compliant is True

    def test_code_compliance_detects_file_write_violation(self):
        """verify_code_compliance() flags 'import pathlib' when side_effects=['none']."""
        contract = BehaviorContract(
            tool_name="file_tool", input_schema={}, output_schema={},
            side_effects=["none"], max_runtime_ms=1000,
        )
        code = '''"""A tool that reads files."""
from pathlib import Path

def file_tool() -> dict:
    return {"files": []}
'''
        result = contract.verify_code_compliance(code)
        assert result.compliant is False
        assert any("pathlib" in v for v in result.violations)

    def test_code_compliance_allows_declared_file_read(self):
        """verify_code_compliance() passes when file_read is declared and pathlib is used."""
        contract = BehaviorContract(
            tool_name="reader_tool", input_schema={}, output_schema={},
            side_effects=["file_read"], max_runtime_ms=1000,
        )
        code = '''"""A file reading tool."""
from pathlib import Path

def reader_tool() -> dict:
    return {"path": str(Path.cwd())}
'''
        result = contract.verify_code_compliance(code)
        assert result.compliant is True

    def test_code_compliance_handles_syntax_error(self):
        """verify_code_compliance() returns non-compliant for unparseable code."""
        contract = BehaviorContract(
            tool_name="broken_tool", input_schema={}, output_schema={},
            side_effects=["none"], max_runtime_ms=1000,
        )
        code = 'def broken('  # SyntaxError
        result = contract.verify_code_compliance(code)
        assert result.compliant is False
        assert any("Syntax error" in v for v in result.violations)

    def test_code_compliance_detects_multiple_violations(self):
        """verify_code_compliance() reports all violations, not just the first."""
        contract = BehaviorContract(
            tool_name="multi_violation_tool", input_schema={}, output_schema={},
            side_effects=["none"], max_runtime_ms=1000,
        )
        code = '''"""A tool with multiple undeclared imports."""
import urllib.parse
from pathlib import Path
from http import client
'''
        result = contract.verify_code_compliance(code)
        assert result.compliant is False
        assert len(result.violations) >= 2
        assert any("urllib" in v for v in result.violations)
        assert any("pathlib" in v for v in result.violations)

    def test_code_compliance_allows_relative_imports(self):
        """verify_code_compliance() allows relative imports without violation."""
        contract = BehaviorContract(
            tool_name="relative_import_tool", input_schema={}, output_schema={},
            side_effects=["none"], max_runtime_ms=1000,
        )
        code = 'from .helper import do_stuff\ndef relative_import_tool() -> dict:\n    return do_stuff()\n'
        result = contract.verify_code_compliance(code)
        # Relative imports are an intentional escape hatch — should not trigger violations
        assert result.compliant is True


# ── Test helpers ─────────────────────────────────────────────────────────

# Import data classes that are used in lambda closures within tests
from tain_agent.evolution.autonomous_loop import (  # noqa: E402
    ToolSnapshot, QualityDelta,
)
import tain_agent.evolution.autonomous_loop as _alo_mod  # noqa: E402


class _MockResponse:
    def __init__(self, text):
        self.text_blocks = [text]
        self.tool_calls = []


class _MockLLM:
    def __init__(self, return_code=None):
        self.call_count = 0
        self._return_code = return_code

    def create_message(self, system_prompt, messages, tools=None):
        self.call_count += 1
        if self._return_code is None:
            return _MockResponse(
                '```python\ndef test_tool(x: int = 0) -> dict:\n'
                '    """A test tool."""\n'
                '    return {"result": x * 2}\n'
                '```\n\n'
                '```contract\n'
                '{"side_effects": ["none"], "max_runtime_ms": 1000}\n'
                '```'
            )
        return _MockResponse(self._return_code)


class _MockToolPlugin:
    """Minimal mock of ToolPlugin for testing AutonomousEvolutionLoop."""

    def __init__(self):
        self._tools = {}
        self._forged = {}

    def list_tools(self):
        return dict(self._tools)

    def get_sandbox_allowlist(self):
        return ["json", "math", "datetime", "collections", "pathlib",
                "typing", "hashlib", "re"]

    def forge_cycle(self, spec, code=None, llm_backend=None):
        from tain_agent.plugins.tool.forge_cycle import (
            ForgeCycleResult, StageResult, CycleStage,
        )
        stages = [
            StageResult(CycleStage.ANALYZE, True, "analyzed"),
            StageResult(CycleStage.DESIGN, True, "designed"),
            StageResult(CycleStage.GENERATE, True, code or "code"),
            StageResult(CycleStage.FORGE, True, {"success": True}),
            StageResult(CycleStage.VERIFY, True, "verified"),
            StageResult(CycleStage.REGISTER, True, "registered"),
        ]
        self._tools[spec.function_name] = {
            "description": spec.description,
            "parameters": spec.parameters,
        }
        if code:
            self._forged[spec.function_name] = code
        return ForgeCycleResult(
            success=True, stages=stages,
            tool_name=spec.function_name, final_code=code,
        )

    def call(self, name, **kwargs):
        if name in self._tools:
            return {"success": True, "result": "ok"}
        return {"success": False, "error": f"Tool '{name}' not found"}

    def list_forged(self):
        return dict(self._forged)

    def rollback(self, tool_name):
        self._tools.pop(tool_name, None)
        self._forged.pop(tool_name, None)
        return {"success": True}


class _MockKnowledgePlugin:
    def __init__(self):
        self._nodes = []

    def query(self, q):
        return self._nodes

    @property
    def node_count(self):
        return len(self._nodes)

    @property
    def goals(self):
        return []


class _MockLineage:
    def __init__(self):
        self.events = []

    def record_forge(self, tool_name, tool_code, agent_version, reasoning=""):
        self.events.append({
            "tool_name": tool_name, "tool_code": tool_code,
            "agent_version": agent_version, "reasoning": reasoning,
        })
        return self.events[-1]

    def record_evolution(self, spec, contract, **kwargs):
        self.events.append({"spec": spec, "contract": contract})


class _VerifyResultMock:
    def __init__(self, consecutive_failures=0):
        self.consecutive_failures = consecutive_failures


# ── Test class ────────────────────────────────────────────────────────────


class TestAutonomousEvolutionLoopUnit:
    """Unit tests for AutonomousEvolutionLoop internal methods."""

    # ── Fixtures ────────────────────────────────────────────────────

    @pytest.fixture
    def mock_backend(self):
        """A mock LLM backend that returns predetermined code."""
        return _MockLLM()

    @pytest.fixture
    def mock_tool_plugin(self):
        return _MockToolPlugin()

    @pytest.fixture
    def mock_knowledge_plugin(self):
        return _MockKnowledgePlugin()

    @pytest.fixture
    def mock_lineage(self):
        return _MockLineage()

    def _make_loop(self, mock_backend, mock_tool_plugin,
                   mock_knowledge_plugin, mock_lineage):
        """Construct AutonomousEvolutionLoop with mocks."""
        from tain_agent.evolution.autonomous_loop import AutonomousEvolutionLoop
        return AutonomousEvolutionLoop(
            mock_backend, mock_tool_plugin,
            mock_knowledge_plugin, mock_lineage,
        )

    # ── parse_generated_response ────────────────────────────────────

    def test_parse_generated_response_extracts_code_and_contract(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """_parse_generated_response extracts code and contract from fenced output."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        response = (
            '```python\ndef foo():\n    pass\n```\n\n'
            '```contract\n{"side_effects": ["none"], "max_runtime_ms": 500}\n```'
        )
        code, contract_json = loop._parse_generated_response(response)
        assert 'def foo():' in code
        assert contract_json == {"side_effects": ["none"], "max_runtime_ms": 500}

    def test_parse_generated_response_handles_no_fences(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """_parse_generated_response falls back to bare text extraction."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        response = 'def foo():\n    pass\n\n{"side_effects": ["none"]}'
        code, contract_json = loop._parse_generated_response(response)
        assert 'def foo():' in code
        assert contract_json == {"side_effects": ["none"]}

    def test_parse_generated_response_handles_code_only_with_contract_text(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """_parse_generated_response extracts JSON contract from text that contains
        'contract' keyword inline (e.g. thoughts)."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        response = (
            '```python\ndef my_tool():\n    pass\n```\n\n'
            '```contract\n{"side_effects": ["network"], "max_runtime_ms": 2000}\n```'
        )
        code, contract_json = loop._parse_generated_response(response)
        assert 'def my_tool():' in code
        assert contract_json == {"side_effects": ["network"], "max_runtime_ms": 2000}

    # ── generate_code ───────────────────────────────────────────────

    def test_generate_code_returns_code_and_contract(
        self, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """_generate_code calls LLM and returns parsed code + contract."""
        from tain_agent.evolution.autonomous_loop import AutonomousEvolutionLoop
        loop = AutonomousEvolutionLoop(
            _MockLLM(), mock_tool_plugin,
            mock_knowledge_plugin, mock_lineage,
        )
        spec = ImprovementSpec(
            capability_id="test_cap",
            description="A test tool",
            function_name="test_func",
            parameters={},
            reasoning="testing",
        )
        code, contract = loop._generate_code(spec)
        assert code is not None
        assert 'def test_tool' in code
        assert contract is not None
        assert contract.side_effects == ["none"]

    def test_generate_code_retry_strips_markdown(
        self, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """_generate_code with retry=True still produces valid output."""
        from tain_agent.evolution.autonomous_loop import AutonomousEvolutionLoop
        loop = AutonomousEvolutionLoop(
            _MockLLM(), mock_tool_plugin,
            mock_knowledge_plugin, mock_lineage,
        )
        spec = ImprovementSpec(
            capability_id="test_cap2",
            description="Another test",
            function_name="another_func",
            parameters={},
            reasoning="retry test",
        )
        code, contract = loop._generate_code(spec, retry=True)
        assert code is not None
        assert contract is not None

    # ── check_contract ──────────────────────────────────────────────

    def test_check_contract_returns_true_for_compliant_code(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """_check_contract returns True for code that matches contract."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        contract = BehaviorContract(
            tool_name="math_tool", input_schema={}, output_schema={},
            side_effects=["none"], max_runtime_ms=1000,
        )
        code = 'import json\nimport math\ndef math_tool(x: float) -> dict:\n    return {"r": x}\n'
        assert loop._check_contract(code, contract) is True

    def test_check_contract_returns_false_for_violating_code(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """_check_contract returns False for code with undeclared imports."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        contract = BehaviorContract(
            tool_name="sneaky_tool", input_schema={}, output_schema={},
            side_effects=["none"], max_runtime_ms=1000,
        )
        code = 'import urllib.parse\ndef sneaky_tool() -> dict:\n    return {}\n'
        assert loop._check_contract(code, contract) is False

    # ── run_one_cycle ───────────────────────────────────────────────

    def test_run_one_cycle_skips_when_no_gaps(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """run_one_cycle returns skipped when _assess_need finds no gaps."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        loop._assess_need = lambda: {
            "should_trigger": False,
            "scores": {},
            "triggered_by": [],
            "need_score": 0.0,
        }
        result = loop.run_one_cycle()
        assert result.skipped is True
        assert result.success is False

    def test_run_one_cycle_full_success(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """run_one_cycle completes all 8 stages successfully."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        # Override internal methods to control behavior
        loop._assess_need = lambda: {
            "should_trigger": True,
            "triggered_by": [{"dimension": "capability_gap", "score": 0.5}],
            "scores": {"capability_gap": 0.5},
            "need_score": 0.5,
        }
        loop._verify_online = lambda name: _VerifyResultMock(0)
        loop._capture_snapshot = lambda tool_name="": ToolSnapshot(
            tool_name="before_snap", code=None,
            tool_list_snapshot={"some_tool": {}},
            forged_list_snapshot={},
            captured_at="2026-01-01T00:00:00",
        )
        loop._evaluate_quality_delta = lambda snap: QualityDelta(degraded=False)

        result = loop.run_one_cycle()
        assert result.success is True
        assert result.spec is not None
        assert result.code is not None
        assert result.contract is not None
        assert result.error == ""

    # ── export_state / execute_once_if_needed ───────────────────────

    def test_export_state_includes_expected_keys(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """export_state returns dict with expected keys."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        state = loop.export_state()
        for key in ("running", "paused", "improvements_this_session",
                     "last_cycle_at", "cycle_history", "trigger_config"):
            assert key in state

    def test_execute_once_if_needed_no_gaps(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """execute_once_if_needed returns triggered=False when no gaps."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        loop._assess_need = lambda: {
            "should_trigger": False,
            "scores": {},
            "triggered_by": [],
            "need_score": 0.0,
        }
        result = loop.execute_once_if_needed()
        assert result["triggered"] is False

    def test_execute_once_if_needed_triggered(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """execute_once_if_needed returns triggered=True and runs a cycle."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        # Clear any persisted state that would cause interval/quota blocking
        loop._last_cycle_at = None
        loop._improvements_this_session = 0
        loop._assess_need = lambda: {
            "should_trigger": True,
            "triggered_by": [{"dimension": "capability_gap", "score": 0.5}],
            "scores": {"capability_gap": 0.5},
            "need_score": 0.5,
        }
        loop._verify_online = lambda name: _VerifyResultMock(0)
        loop._capture_snapshot = lambda tool_name="": ToolSnapshot(
            tool_name="snap", code=None,
            tool_list_snapshot={}, forged_list_snapshot={},
            captured_at="2026-01-01T00:00:00",
        )
        loop._evaluate_quality_delta = lambda snap: QualityDelta(degraded=False)
        result = loop.execute_once_if_needed()
        assert result["triggered"] is True
        assert "result" in result

    # ── _assess_need / dimension evaluators ─────────────────────────

    def test_assess_need_includes_all_dimensions(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """_assess_need returns scores for all 8 dimensions."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        result = loop._assess_need()
        assert "should_trigger" in result
        assert "scores" in result
        assert "triggered_by" in result
        assert "need_score" in result
        # All 8 dimensions should be present
        expected_dims = {
            "capability_gap", "code_health", "knowledge_fresh",
            "tool_fitness", "tool_dedup", "subgraph_balance",
            "task_completion", "goal_achievement",
        }
        assert set(result["scores"].keys()) == expected_dims

    def test_eval_capability_gap_zero_when_enough_tools(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """_eval_capability_gap returns 0 when >=10 tools registered."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        for i in range(10):
            mock_tool_plugin._tools[f"tool_{i}"] = {"description": f"Tool {i}"}
        score = loop._eval_capability_gap()
        assert score == 0.0

    def test_eval_capability_gap_positive_when_few_tools(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """_eval_capability_gap returns positive when few tools registered."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        # Only 2 tools → should detect a gap
        mock_tool_plugin._tools["tool_a"] = {"description": "Tool A"}
        mock_tool_plugin._tools["tool_b"] = {"description": "Tool B"}
        score = loop._eval_capability_gap()
        assert 0 <= score <= 1

    def test_eval_tool_dedup_uses_hash_based_dedup(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """_eval_tool_dedup returns float based on forged tool list."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        score = loop._eval_tool_dedup()
        assert 0 <= score <= 1

    def test_eval_task_completion_returns_zero_stub(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """_eval_task_completion returns 0.0 (stub — needs decision_log)."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        score = loop._eval_task_completion()
        assert score == 0.0

    def test_eval_goal_achievement_queries_knowledge_plugin(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """_eval_goal_achievement gracefully handles knowledge plugin."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        score = loop._eval_goal_achievement()
        assert 0 <= score <= 1

    # ── configure / start / stop / pause / resume ───────────────────

    def test_configure_applies_overrides(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """configure() applies config overrides."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        loop.configure(
            min_interval_seconds=600,
            max_improvements_per_session=5,
            contract_enforcement="warn",
        )
        assert loop.min_interval_seconds == 600
        assert loop.max_improvements_per_session == 5
        assert loop.contract_enforcement == "warn"

    def test_start_returns_state(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """start() returns state dict and sets _running."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        result = loop.start()
        assert loop._running is True
        assert "running" in result
        result2 = loop.start()
        assert result2["success"] is False  # already running

    def test_stop_stops_loop(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """stop() stops a running loop."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        loop.start()
        result = loop.stop()
        assert loop._running is False
        assert "running" in result

    def test_pause_resume_cycle(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """pause() and resume() toggle the paused state."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        loop._running = True
        result = loop.pause()
        assert loop._paused is True
        assert "paused" in result
        result = loop.resume()
        assert loop._paused is False

    # ── _generate_spec ──────────────────────────────────────────────

    def test_generate_spec_returns_improvement_spec(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """_generate_spec returns an ImprovementSpec for a given assessment."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        assessment = {
            "triggered_by": [{"dimension": "capability_gap", "score": 0.5}],
            "scores": {"capability_gap": 0.5},
        }
        spec = loop._generate_spec(assessment)
        assert spec is not None
        assert spec.function_name.startswith("auto_capability_gap")
        assert spec.description != ""
        assert spec.reasoning != ""

    def test_generate_spec_increments_function_name(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """_generate_spec creates unique function names to avoid collisions."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        assessment = {
            "triggered_by": [{"dimension": "tool_dedup", "score": 0.6}],
            "scores": {"tool_dedup": 0.6},
        }
        spec1 = loop._generate_spec(assessment)
        spec2 = loop._generate_spec(assessment)
        assert spec1.function_name != spec2.function_name

    # ── _build_generation_prompt ────────────────────────────────────

    def test_build_generation_prompt_includes_spec_details(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """_build_generation_prompt includes spec function_name and description."""
        loop = self._make_loop(mock_backend, mock_tool_plugin,
                               mock_knowledge_plugin, mock_lineage)
        spec = ImprovementSpec(
            capability_id="test_build",
            description="Build a test function",
            function_name="my_built_func",
            parameters={"param1": {"type": "string"}},
            reasoning="need it",
        )
        prompt = loop._build_generation_prompt(spec)
        assert "my_built_func" in prompt
        assert "Build a test function" in prompt

    # ── ToolSnapshot dataclass ──────────────────────────────────────

    def test_tool_snapshot_creation(
        self, mock_backend, mock_tool_plugin, mock_knowledge_plugin, mock_lineage,
    ):
        """ToolSnapshot dataclass creates correctly."""
        from tain_agent.evolution.autonomous_loop import ToolSnapshot
        snap = ToolSnapshot(
            tool_name="test_tool",
            code="def test_tool(): pass",
            tool_list_snapshot={"a": {}},
            forged_list_snapshot={},
            captured_at="2026-01-01T00:00:00",
        )
        assert snap.tool_name == "test_tool"
        assert snap.code == "def test_tool(): pass"

    # ── QualityDelta dataclass ──────────────────────────────────────

    def test_quality_delta_default_not_degraded(self):
        """QualityDelta defaults to not degraded with empty reason."""
        from tain_agent.evolution.autonomous_loop import QualityDelta
        qd = QualityDelta()
        assert qd.degraded is False
        assert qd.reason == ""

    # ── CycleResult dataclass ───────────────────────────────────────

    def test_cycle_result_skipped_factory(self):
        """CycleResult.skipped_result creates a properly initialized instance."""
        from tain_agent.evolution.autonomous_loop import CycleResult
        result = CycleResult.skipped_result({"need_score": 0.0, "scores": {}})
        assert result.skipped is True
        assert result.success is False

    def test_cycle_result_failed_factory(self):
        """CycleResult.failed creates an instance with error and stage."""
        from tain_agent.evolution.autonomous_loop import CycleResult
        result = CycleResult.failed("CONTRACT_CHECK", error="Import violation")
        assert result.success is False
        assert result.stage == "CONTRACT_CHECK"
        assert result.error == "Import violation"

    def test_cycle_result_success_factory(self):
        """CycleResult.success_result creates a success instance."""
        from tain_agent.evolution.autonomous_loop import CycleResult
        spec = ImprovementSpec("cid", "desc", "fn", {}, "why")
        contract = BehaviorContract("fn", {}, {}, ["none"], 1000)
        result = CycleResult.success_result(spec, "def fn(): pass", contract)
        assert result.success is True
        assert result.spec is spec
        assert result.code == "def fn(): pass"
