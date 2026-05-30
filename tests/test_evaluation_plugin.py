"""Tests for EvaluationPlugin — models, engine, reporter, gate, triggers."""

from tain_agent.plugins.evaluation.models import (
    MaturityTier, TrendDirection, DimensionMaturity,
    EvaluationSnapshot, EvaluationReport, Risk, ActionItem,
    ProductionStatus, ProductionReadiness, ScenarioResult,
)
from tain_agent.plugins.evaluation.engine import MaturityEngine
from tain_agent.plugins.evaluation.triggers import TriggerManager


class TestMaturityTier:
    def test_tier_values(self):
        assert MaturityTier.NASCENT.value == 1
        assert MaturityTier.EXCELLENT.value == 5

    def test_tier_from_score(self):
        assert DimensionMaturity._score_to_tier(0.1) == MaturityTier.NASCENT
        assert DimensionMaturity._score_to_tier(0.35) == MaturityTier.DEVELOPING
        assert DimensionMaturity._score_to_tier(0.6) == MaturityTier.CAPABLE
        assert DimensionMaturity._score_to_tier(0.8) == MaturityTier.MATURE
        assert DimensionMaturity._score_to_tier(0.95) == MaturityTier.EXCELLENT


class TestDimensionMaturity:
    def test_create_dimension(self):
        dm = DimensionMaturity(
            dimension="skill", score=0.72, level=MaturityTier.CAPABLE,
            trend=TrendDirection.IMPROVING,
            evidence=["5 skills, avg success 0.85"],
            recommendations=["compose skills into new capability"],
        )
        assert dm.score == 0.72
        assert dm.level == MaturityTier.CAPABLE


class TestEvaluationSnapshot:
    def test_overall_score_weighted_average(self):
        WEIGHTS = {"identity": 0.15, "memory": 0.10, "skill": 0.20, "tool": 0.20,
                   "knowledge": 0.15, "workflow": 0.10, "collaboration": 0.10}
        dimensions = {}
        for dim, w in WEIGHTS.items():
            dimensions[dim] = DimensionMaturity(
                dimension=dim, score=0.8, level=MaturityTier.MATURE,
                trend=TrendDirection.STABLE, evidence=[], recommendations=[],
            )
        snap = EvaluationSnapshot(agent_id="a1", dimensions=dimensions)
        assert abs(snap.overall_score - 0.8) < 0.01

    def test_radar_data_flat_dict(self):
        dims = {
            "identity": DimensionMaturity(dimension="identity", score=0.5, level=MaturityTier.CAPABLE),
            "skill": DimensionMaturity(dimension="skill", score=0.9, level=MaturityTier.EXCELLENT),
        }
        snap = EvaluationSnapshot(agent_id="a1", dimensions=dims)
        assert snap.radar_data == {"identity": 0.5, "skill": 0.9}


class TestProductionReadiness:
    def test_not_ready_by_default(self):
        pr = ProductionReadiness()
        assert pr.status == ProductionStatus.NOT_READY

    def test_ready_for_trial_when_streak_met_and_no_scenarios(self):
        pr = ProductionReadiness(stable_streak=3, required_streak=3)
        assert pr.status == ProductionStatus.READY_FOR_TRIAL

    def test_production_ready_when_scenarios_pass(self):
        pr = ProductionReadiness(
            stable_streak=3, required_streak=3,
            scenario_results=[ScenarioResult(task_name="test", passed=True)],
        )
        assert pr.status == ProductionStatus.PRODUCTION_READY


class TestMaturityEngine:
    def _make_engine(self):
        return MaturityEngine()

    def test_compute_dimension_from_health_metrics(self):
        engine = self._make_engine()
        dm = engine._compute_dimension("skill", {
            "total_skills": 8, "expert_skills": 2, "master_skills": 1,
            "avg_success_rate": 0.85, "composed_count": 3,
        })
        assert dm.score > 0.5
        assert dm.level in (MaturityTier.CAPABLE, MaturityTier.MATURE, MaturityTier.EXCELLENT)

    def test_compute_dimension_with_empty_data(self):
        engine = self._make_engine()
        dm = engine._compute_dimension("tool", {})
        assert dm.score == 0.0
        assert dm.level == MaturityTier.NASCENT

    def test_detect_trend_improving(self):
        engine = self._make_engine()
        engine._score_history = {"skill": [0.5, 0.52, 0.65]}
        trend = engine._detect_trend("skill", 0.65)
        assert trend == TrendDirection.IMPROVING

    def test_detect_trend_declining(self):
        engine = self._make_engine()
        engine._score_history = {"tool": [0.8, 0.75, 0.60]}
        trend = engine._detect_trend("tool", 0.60)
        assert trend == TrendDirection.DECLINING

    def test_detect_trend_stable_first_eval(self):
        engine = self._make_engine()
        trend = engine._detect_trend("knowledge", 0.55)
        assert trend == TrendDirection.STABLE

    def test_full_evaluate_produces_snapshot(self):
        engine = self._make_engine()
        plugin_metrics = {
            "identity": {"expertise_count": 3, "values_count": 5, "autonomy_level": 2, "traits_median_confidence": 0.6},
            "memory": {"episodic_count": 30, "semantic_entities": 15, "median_strength": 0.7},
            "skill": {"total_skills": 5, "expert_skills": 1, "master_skills": 0, "avg_success_rate": 0.7, "composed_count": 1},
            "tool": {"total_tools": 15, "forged_tools": 3, "call_success_rate": 0.9, "forge_cycle_success_rate": 0.7},
            "knowledge": {"entity_count": 25, "relation_density": 0.5, "freshness_ratio": 0.8},
            "workflow": {"completed_count": 10, "success_rate": 0.85, "avg_steps": 4},
            "collaboration": {"collab_count": 3, "team_count": 1, "reputation": 60, "teach_count": 0},
        }
        snap = engine.evaluate("agent-1", plugin_metrics)
        assert snap.agent_id == "agent-1"
        assert len(snap.dimensions) == 7
        assert snap.overall_score > 0
        for dim in ["identity", "memory", "skill", "tool", "knowledge", "workflow", "collaboration"]:
            assert dim in snap.dimensions


class TestTriggerManager:
    def test_first_cycle_no_trigger(self):
        tm = TriggerManager(routine_interval=50, deep_interval=200)
        tm.on_cycle(1)
        assert tm.should_run_routine is False
        assert tm.should_run_deep is False

    def test_routine_trigger_at_interval(self):
        tm = TriggerManager(routine_interval=50, deep_interval=200)
        tm.on_cycle(50)
        assert tm.should_run_routine is True
        assert tm.should_run_deep is False

    def test_deep_trigger_at_interval(self):
        tm = TriggerManager(routine_interval=50, deep_interval=200)
        tm.on_cycle(200)
        assert tm.should_run_routine is True
        assert tm.should_run_deep is True

    def test_event_triggers_key_events(self):
        tm = TriggerManager()
        assert tm.is_event_trigger("tool.forge.failure", 3) is True
        assert tm.is_event_trigger("skill.maturity.upgrade", 1) is True
        assert tm.is_event_trigger("collaboration.teach.complete", 1) is True

    def test_event_not_triggered_below_threshold(self):
        tm = TriggerManager()
        assert tm.is_event_trigger("tool.forge.failure", 1) is False

    def test_reset_after_trigger(self):
        tm = TriggerManager(routine_interval=50, deep_interval=200)
        tm.on_cycle(50)
        assert tm.should_run_routine is True
        reset = tm.consume()
        assert reset["routine"] is True
        assert tm.should_run_routine is False
