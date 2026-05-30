"""Tests for EvaluationPlugin — models, engine, reporter, gate, triggers."""

from tain_agent.plugins.evaluation.models import (
    MaturityTier, TrendDirection, DimensionMaturity,
    EvaluationSnapshot, EvaluationReport, Risk, ActionItem,
    ProductionStatus, ProductionReadiness, ScenarioResult,
)


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
