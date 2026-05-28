"""Tests for the quality gate evaluation system."""

import pytest
from unittest.mock import MagicMock


class TestScoredResult:
    def test_create(self):
        from tain_agent.evolution.quality_gate import ScoredResult
        r = ScoredResult("S1", "Test Gate", 0.85, 0.25, "All good")
        assert r.gate_id == "S1"
        assert r.label == "Test Gate"
        assert r.score == 0.85
        assert r.weight == 0.25
        assert r.detail == "All good"


class TestS1ToolSuccessRate:
    def test_no_agent(self):
        from tain_agent.evolution.quality_gate import _s1_tool_success_rate
        result = _s1_tool_success_rate(None)
        assert result.gate_id == "S1"
        assert result.score == 0.50

    def test_with_cognitive_loop_data(self):
        from tain_agent.evolution.quality_gate import _s1_tool_success_rate
        agent = MagicMock()
        cognitive = MagicMock()
        cognitive._tool_success_rates = {
            "read_file": (8, 10),
            "web_search": (3, 3),
        }
        agent.cognitive_loop = cognitive
        result = _s1_tool_success_rate(agent)
        # (8+3)/(10+3) = 11/13 ≈ 0.846
        assert 0.8 < result.score < 0.9

    def test_no_data_yet(self):
        from tain_agent.evolution.quality_gate import _s1_tool_success_rate
        agent = MagicMock()
        cognitive = MagicMock()
        cognitive._tool_success_rates = {}
        agent.cognitive_loop = cognitive
        result = _s1_tool_success_rate(agent)
        assert result.score == 0.50


class TestS4ActionDiversity:
    def test_no_agent(self):
        from tain_agent.evolution.quality_gate import _s4_action_diversity
        result = _s4_action_diversity(None)
        assert result.gate_id == "S4"
        assert result.score == 0.50

    def test_high_diversity(self):
        from tain_agent.evolution.quality_gate import _s4_action_diversity
        agent = MagicMock()
        cognitive = MagicMock()
        cognitive._action_history = [
            "read_file", "web_search", "write_file", "explore_directory",
            "web_fetch", "execute_code", "forge_tool", "set_goal",
            "observe_environment", "record_decision",
        ]
        agent.cognitive_loop = cognitive
        result = _s4_action_diversity(agent)
        assert result.score >= 0.7

    def test_low_diversity(self):
        from tain_agent.evolution.quality_gate import _s4_action_diversity
        agent = MagicMock()
        cognitive = MagicMock()
        cognitive._action_history = ["read_file"] * 20
        agent.cognitive_loop = cognitive
        result = _s4_action_diversity(agent)
        assert result.score < 0.5


class TestGateReport:
    def test_empty_report(self):
        from tain_agent.evolution.quality_gate import GateReport
        r = GateReport(agent_name="test", agent_version="0.1.0")
        assert r.agent_name == "test"
        assert r.hard_passed is True  # vacuously

    def test_with_hard_failure(self):
        from tain_agent.evolution.quality_gate import GateReport, GateResult
        r = GateReport(agent_name="test", agent_version="0.1.0")
        r.hard_results.append(GateResult("H1", "Test", False, "failed"))
        assert r.hard_passed is False

    def test_with_scoring(self):
        from tain_agent.evolution.quality_gate import GateReport, ScoredResult
        r = GateReport(agent_name="test", agent_version="0.1.0")
        r.scoring_results.append(ScoredResult("S1", "Test", 0.8, 0.25, ""))
        r.scoring_results.append(ScoredResult("S2", "Test", 0.6, 0.15, ""))
        # total_score is sum of weighted scores: 0.8*0.25 + 0.6*0.15 = 0.29
        score = r.total_score
        assert 0.25 < score < 0.35
