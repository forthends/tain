"""Data models for the evaluation system."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MaturityTier(Enum):
    NASCENT = 1
    DEVELOPING = 2
    CAPABLE = 3
    MATURE = 4
    EXCELLENT = 5


class TrendDirection(Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"


class ProductionStatus(Enum):
    NOT_READY = "not_ready"
    STABILIZING = "stabilizing"
    READY_FOR_TRIAL = "ready_for_trial"
    PRODUCTION_READY = "production_ready"


@dataclass
class DimensionMaturity:
    dimension: str
    score: float
    level: MaturityTier = MaturityTier.NASCENT
    trend: TrendDirection = TrendDirection.STABLE
    evidence: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    evaluated_at: str = field(default_factory=_now)

    @staticmethod
    def _score_to_tier(score: float) -> MaturityTier:
        if score < 0.2:
            return MaturityTier.NASCENT
        elif score < 0.5:
            return MaturityTier.DEVELOPING
        elif score < 0.75:
            return MaturityTier.CAPABLE
        elif score < 0.9:
            return MaturityTier.MATURE
        return MaturityTier.EXCELLENT

    def __post_init__(self):
        if not self.level and self.score is not None:
            self.level = self._score_to_tier(self.score)


@dataclass
class EvaluationSnapshot:
    agent_id: str
    dimensions: dict[str, DimensionMaturity] = field(default_factory=dict)
    evaluated_at: str = field(default_factory=_now)
    report_id: str = ""
    production_readiness: ProductionReadiness | None = None

    @property
    def overall_score(self) -> float:
        WEIGHTS = {"identity": 0.15, "memory": 0.10, "skill": 0.20, "tool": 0.20,
                   "knowledge": 0.15, "workflow": 0.10, "collaboration": 0.10}
        total = 0.0
        weight_sum = 0.0
        for dim, w in WEIGHTS.items():
            if dim in self.dimensions:
                total += self.dimensions[dim].score * w
                weight_sum += w
        return round(total / weight_sum, 4) if weight_sum > 0 else 0.0

    @property
    def radar_data(self) -> dict[str, float]:
        return {k: v.score for k, v in self.dimensions.items()}


@dataclass
class Risk:
    dimension: str
    severity: str  # "critical" | "warning"
    description: str
    current_score: float
    trend: str = ""


@dataclass
class ActionItem:
    priority: int  # 1 = highest
    dimension: str
    description: str
    goal_title: str
    suggested_workflow: list[str] = field(default_factory=list)
    expected_impact: float = 0.0


@dataclass
class EvaluationReport:
    report_id: str
    agent_id: str
    agent_name: str = ""
    evaluated_at: str = field(default_factory=_now)
    dimensions: dict[str, DimensionMaturity] = field(default_factory=dict)
    radar_data: dict[str, float] = field(default_factory=dict)
    trend_summary: dict[str, str] = field(default_factory=dict)
    historical_scores: list[dict] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    risks: list[Risk] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)
    production_readiness: ProductionReadiness | None = None


@dataclass
class ScenarioResult:
    task_name: str
    task_description: str = ""
    passed: bool = False
    evidence: dict = field(default_factory=dict)
    evaluated_by: str = "framework"
    notes: str = ""


@dataclass
class ProductionReadiness:
    status: ProductionStatus = ProductionStatus.NOT_READY
    stable_streak: int = 0
    required_streak: int = 3
    scenario_results: list[ScenarioResult] = field(default_factory=list)
    certified_at: str | None = None
    certification_report_id: str | None = None

    def __post_init__(self):
        if self.stable_streak >= self.required_streak:
            if self.scenario_results:
                all_passed = all(r.passed for r in self.scenario_results)
                self.status = ProductionStatus.PRODUCTION_READY if all_passed else ProductionStatus.READY_FOR_TRIAL
            else:
                if self.status == ProductionStatus.NOT_READY:
                    self.status = ProductionStatus.READY_FOR_TRIAL
