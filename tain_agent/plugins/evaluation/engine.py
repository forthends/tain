"""MaturityEngine — seven-dimension evaluation with trend detection."""

from __future__ import annotations
import uuid
from tain_agent.plugins.evaluation.models import (
    DimensionMaturity, MaturityTier, TrendDirection, EvaluationSnapshot,
)


SCORE_FORMULAS = {
    "identity": lambda m: min(1.0, (
        0.25 * min(m.get("expertise_count", 0) / 3.0, 1.0) +
        0.20 * min(m.get("values_count", 0) / 4.0, 1.0) +
        0.20 * min(m.get("autonomy_level", 1) / 5.0, 1.0) +
        0.35 * min(m.get("traits_median_confidence", 0) / 0.8, 1.0)
    )),
    "memory": lambda m: min(1.0, (
        0.35 * min(m.get("episodic_count", 0) / 50.0, 1.0) +
        0.35 * min(m.get("semantic_entities", 0) / 20.0, 1.0) +
        0.30 * min(m.get("median_strength", 0) / 0.8, 1.0)
    )),
    "skill": lambda m: min(1.0, (
        0.25 * min(m.get("total_skills", 0) / 5.0, 1.0) +
        0.25 * min((m.get("expert_skills", 0) + m.get("master_skills", 0)) / 2.0, 1.0) +
        0.30 * min(m.get("avg_success_rate", 0), 1.0) +
        0.20 * min(m.get("composed_count", 0) / 2.0, 1.0)
    )),
    "tool": lambda m: min(1.0, (
        0.20 * min(m.get("total_tools", 0) / 10.0, 1.0) +
        0.25 * min(m.get("forged_tools", 0) / 3.0, 1.0) +
        0.35 * min(m.get("call_success_rate", 0), 1.0) +
        0.20 * min(m.get("forge_cycle_success_rate", 0), 1.0)
    )),
    "knowledge": lambda m: min(1.0, (
        0.40 * min(m.get("entity_count", 0) / 30.0, 1.0) +
        0.35 * min(m.get("relation_density", 0) / 0.5, 1.0) +
        0.25 * min(m.get("freshness_ratio", 0), 1.0)
    )),
    "workflow": lambda m: min(1.0, (
        0.35 * min(m.get("completed_count", 0) / 10.0, 1.0) +
        0.35 * min(m.get("success_rate", 0), 1.0) +
        0.30 * min(m.get("avg_steps", 0) / 5.0, 1.0)
    )),
    "collaboration": lambda m: min(1.0, (
        0.30 * min(m.get("collab_count", 0) / 5.0, 1.0) +
        0.25 * min(m.get("team_count", 0) / 2.0, 1.0) +
        0.25 * min(m.get("reputation", 0) / 80.0, 1.0) +
        0.20 * min(m.get("teach_count", 0) / 2.0, 1.0)
    )),
}

IMPROVEMENT_THRESHOLD = 0.05


class MaturityEngine:
    """Computes seven-dimension maturity scores from plugin health metrics."""

    def __init__(self):
        self._score_history: dict[str, list[float]] = {
            dim: [] for dim in SCORE_FORMULAS
        }

    def evaluate(self, agent_id: str, plugin_metrics: dict[str, dict]) -> EvaluationSnapshot:
        dimensions: dict[str, DimensionMaturity] = {}
        for dim in SCORE_FORMULAS:
            metrics = plugin_metrics.get(dim, {})
            dm = self._compute_dimension(dim, metrics)
            dimensions[dim] = dm
            self._score_history[dim].append(dm.score)
            if len(self._score_history[dim]) > 20:
                self._score_history[dim] = self._score_history[dim][-20:]

        return EvaluationSnapshot(
            agent_id=agent_id,
            dimensions=dimensions,
            report_id=f"eval_{uuid.uuid4().hex[:12]}",
        )

    def _compute_dimension(self, dim: str, metrics: dict) -> DimensionMaturity:
        if not metrics:
            return DimensionMaturity(
                dimension=dim, score=0.0, level=MaturityTier.NASCENT,
                trend=TrendDirection.STABLE,
                evidence=["no data available"],
                recommendations=["start using this capability"],
            )

        formula = SCORE_FORMULAS.get(dim, lambda m: 0.0)
        score = round(formula(metrics), 4)
        level = DimensionMaturity._score_to_tier(score)
        trend = self._detect_trend(dim, score)

        evidence = [f"{k}: {v}" for k, v in list(metrics.items())[:3]]
        recommendations = self._generate_recommendations(dim, score)
        return DimensionMaturity(
            dimension=dim, score=score, level=level, trend=trend,
            evidence=evidence, recommendations=recommendations,
        )

    def _detect_trend(self, dim: str, current: float) -> TrendDirection:
        history = self._score_history.get(dim, [])
        if len(history) < 2:
            return TrendDirection.STABLE
        prev_avg = sum(history[-3:-1]) / max(len(history[-3:-1]), 1)
        if current > prev_avg + IMPROVEMENT_THRESHOLD:
            return TrendDirection.IMPROVING
        elif current < prev_avg - IMPROVEMENT_THRESHOLD:
            return TrendDirection.DECLINING
        return TrendDirection.STABLE

    def _generate_recommendations(self, dim: str, score: float) -> list[str]:
        recs = {
            "identity": {
                (0, 0.5): ["探索自身定位，发现更多人格特质"],
                (0.5, 0.75): ["申请自主等级升级"],
                (0.75, 1.1): ["撰写自身能力白皮书"],
            },
            "memory": {
                (0, 0.5): ["巩固重要的情景记忆"],
                (0.5, 0.75): ["提取记忆模式到语义记忆"],
                (0.75, 1.1): ["清理劣化记忆，整理记忆库"],
            },
            "skill": {
                (0, 0.5): ["练习已有技能，提高成功率"],
                (0.5, 0.75): ["组合技能形成新能力"],
                (0.75, 1.1): ["传授技能给其他 Agent"],
            },
            "tool": {
                (0, 0.5): ["运行 forge_cycle 填补工具缺口"],
                (0.5, 0.75): ["优化已有工具，提高成功率"],
                (0.75, 1.1): ["审计工具安全性并文档化"],
            },
            "knowledge": {
                (0, 0.5): ["扩展知识面，增加实体和关系"],
                (0.5, 0.75): ["验证过期知识，更新新鲜度"],
                (0.75, 1.1): ["导出知识子图，传授他人"],
            },
            "workflow": {
                (0, 0.5): ["完成简单工作流练习"],
                (0.5, 0.75): ["执行复杂多步骤工作流"],
                (0.75, 1.1): ["从成功经验中提取工作流模板"],
            },
            "collaboration": {
                (0, 0.5): ["主动与其他 Agent 建立联系"],
                (0.5, 0.75): ["组建或加入团队协作"],
                (0.75, 1.1): ["传授技能给其他 Agent"],
            },
        }
        for (lo, hi), recs_list in recs.get(dim, {}).items():
            if lo <= score < hi:
                return recs_list
        return ["保持当前水平，持续优化"]
