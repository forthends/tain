"""ProductionGate — determines if an agent is ready for production deployment."""

from __future__ import annotations
from datetime import datetime, timezone
from tain_agent.plugins.evaluation.models import (
    EvaluationSnapshot, ProductionReadiness, ProductionStatus, ScenarioResult,
    DimensionMaturity, TrendDirection,
)

ALL_DIMENSIONS = ["identity", "memory", "skill", "tool", "knowledge", "workflow", "collaboration"]
PRODUCTION_THRESHOLD = 0.75

SCENARIO_TEMPLATES = {
    "coding": {
        "task_name": "独立开发验收",
        "description": "根据需求描述独立完成一个功能模块的完整开发流程",
        "steps": ["需求分析 → 设计 → 代码生成 → 测试 → 文档"],
        "success_criteria": {"tool_success_rate": 0.8, "test_pass_rate": 1.0},
    },
    "analysis": {
        "task_name": "数据分析验收",
        "description": "对给定数据集完成端到端分析并输出报告",
        "steps": ["数据获取 → 清洗 → 分析 → 可视化 → 报告"],
        "success_criteria": {"tool_chain_success": 0.9},
    },
    "general": {
        "task_name": "综合能力验收",
        "description": "自主识别一个问题，设计解决方案并执行完成",
        "steps": ["问题识别 → 方案设计 → 工具使用 → 结果验证 → 总结"],
        "success_criteria": {"action_diversity": 0.5, "completion_rate": 1.0},
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProductionGate:
    """Evaluates production readiness based on maturity snapshots and scenario verification."""

    def __init__(self, required_streak: int = 3):
        self.required_streak = required_streak

    def evaluate(self, snapshot: EvaluationSnapshot,
                 history: list[EvaluationSnapshot]) -> ProductionReadiness:
        """Determine readiness from current snapshot + history."""
        all_pass = all(
            snapshot.dimensions.get(d, DimensionMaturity(dimension=d, score=0)).score >= PRODUCTION_THRESHOLD
            for d in ALL_DIMENSIONS
        )
        no_critical_risks = all(
            snapshot.dimensions[d].trend != TrendDirection.DECLINING
            for d in ALL_DIMENSIONS if d in snapshot.dimensions
        )

        if not (all_pass and no_critical_risks):
            return ProductionReadiness(status=ProductionStatus.NOT_READY)

        # Count stable streak
        streak = 1
        if history:
            for past in reversed(history[:-1]):
                if past.agent_id != snapshot.agent_id:
                    break
                past_all_pass = all(
                    past.dimensions.get(d, DimensionMaturity(dimension=d, score=0)).score >= PRODUCTION_THRESHOLD
                    for d in ALL_DIMENSIONS
                )
                if past_all_pass:
                    streak += 1
                else:
                    break

        readiness = ProductionReadiness(
            stable_streak=streak,
            required_streak=self.required_streak,
        )

        if streak >= self.required_streak:
            readiness.status = ProductionStatus.READY_FOR_TRIAL
        elif all_pass:
            readiness.status = ProductionStatus.STABILIZING

        return readiness

    def get_scenario_template(self, agent_role: str) -> dict:
        """Return the appropriate scenario template for the agent's role."""
        for key in SCENARIO_TEMPLATES:
            if key in agent_role.lower():
                return SCENARIO_TEMPLATES[key]
        return SCENARIO_TEMPLATES["general"]

    def request_scenario_verification(self, agent_role: str) -> ScenarioResult:
        """Generate a scenario verification task."""
        template = self.get_scenario_template(agent_role)
        return ScenarioResult(
            task_name=template["task_name"],
            task_description=template["description"],
            evidence={"template": template},
        )

    def certify(self, readiness: ProductionReadiness) -> None:
        """Certify agent as production ready."""
        if readiness.scenario_results and all(r.passed for r in readiness.scenario_results):
            readiness.status = ProductionStatus.PRODUCTION_READY
            readiness.certified_at = _now()
