"""EvaluationReporter — generates executable evaluation reports with action items."""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from tain_agent.plugins.evaluation.models import (
    EvaluationSnapshot, EvaluationReport, Risk, ActionItem, DimensionMaturity,
    TrendDirection, ProductionReadiness,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvaluationReporter:
    """Generates evaluation reports from snapshots, with strengths, risks, and action items."""

    def generate(self, snapshot: EvaluationSnapshot, agent_name: str = "",
                 history: list[dict] | None = None,
                 readiness: ProductionReadiness | None = None) -> EvaluationReport:
        report_id = f"rpt_{uuid.uuid4().hex[:12]}"

        strengths = self._identify_strengths(snapshot)
        risks = self._identify_risks(snapshot)
        action_items = self._generate_action_items(snapshot)
        trend_summary = {
            dim: "↑" if d.trend == TrendDirection.IMPROVING
            else "↓" if d.trend == TrendDirection.DECLINING else "→"
            for dim, d in snapshot.dimensions.items()
        }

        return EvaluationReport(
            report_id=report_id,
            agent_id=snapshot.agent_id,
            agent_name=agent_name,
            evaluated_at=_now(),
            dimensions=snapshot.dimensions,
            radar_data=snapshot.radar_data,
            trend_summary=trend_summary,
            historical_scores=history or [],
            strengths=strengths,
            risks=risks,
            action_items=action_items,
            production_readiness=readiness,
        )

    def _identify_strengths(self, snap: EvaluationSnapshot) -> list[str]:
        strengths = []
        for dim, d in snap.dimensions.items():
            if d.score >= 0.75 and d.trend != TrendDirection.DECLINING:
                strengths.append(f"{dim}: score={d.score:.2f}, trend={d.trend.value}")
        return strengths

    def _identify_risks(self, snap: EvaluationSnapshot) -> list[Risk]:
        risks = []
        for dim, d in snap.dimensions.items():
            if d.score < 0.5:
                risks.append(Risk(
                    dimension=dim, severity="critical" if d.score < 0.3 else "warning",
                    description=f"Low maturity in {dim}", current_score=d.score,
                    trend=d.trend.value,
                ))
            elif d.trend == TrendDirection.DECLINING:
                risks.append(Risk(
                    dimension=dim, severity="warning",
                    description=f"Declining trend in {dim}", current_score=d.score,
                    trend="declining",
                ))
        return risks

    def _generate_action_items(self, snap: EvaluationSnapshot) -> list[ActionItem]:
        items = []
        for dim, d in snap.dimensions.items():
            if d.score >= 0.9:
                continue
            priority = 1 if d.score < 0.3 else (2 if d.score < 0.5 else 3)
            goal = d.recommendations[0] if d.recommendations else f"improve {dim}"
            items.append(ActionItem(
                priority=priority, dimension=dim,
                description=f"维度 {dim} 当前得分 {d.score:.2f}，建议: {goal}",
                goal_title=goal,
                suggested_workflow=[goal],
                expected_impact=round((0.8 - d.score) * 0.3, 2),
            ))
        items.sort(key=lambda a: (a.priority, -a.expected_impact))
        return items

    def render_markdown(self, report: EvaluationReport) -> str:
        """Render an evaluation report as Markdown."""
        lines = [
            f"# Evaluation Report — {report.agent_name}",
            f"**Agent**: {report.agent_id}  ",
            f"**Evaluated**: {report.evaluated_at[:19]}  ",
            f"**Report ID**: {report.report_id}",
            "",
            "---",
            "",
            "## Maturity Dashboard",
            "",
            "| Dimension | Score | Level | Trend |",
            "|-----------|-------|-------|-------|",
        ]
        for dim, d in report.dimensions.items():
            bar = "█" * int(d.score * 10) + "░" * (10 - int(d.score * 10))
            trend_icon = report.trend_summary.get(dim, "→")
            lines.append(f"| {dim} | {d.score:.2f} {bar} | {d.level.name} | {trend_icon} |")

        overall = sum(d.score for d in report.dimensions.values()) / max(len(report.dimensions), 1)
        lines.extend(["", f"**Overall Score**: {overall:.3f}", ""])

        if report.strengths:
            lines.extend(["## Strengths", ""])
            for s in report.strengths:
                lines.append(f"- ✅ {s}")

        if report.risks:
            lines.extend(["", "## Risks", ""])
            for r in report.risks:
                icon = "🔴" if r.severity == "critical" else "🟡"
                lines.append(f"- {icon} **{r.dimension}**: {r.description} (score={r.current_score:.2f})")

        if report.action_items:
            lines.extend(["", "## Recommended Actions", ""])
            for item in report.action_items[:5]:
                lines.append(f"- **P{item.priority}** [{item.dimension}] {item.description}")

        if report.production_readiness:
            pr = report.production_readiness
            lines.extend(["", "## Production Readiness", "",
                          f"- Status: **{pr.status.value}**",
                          f"- Stable streak: {pr.stable_streak}/{pr.required_streak}",
            ])

        return "\n".join(lines)
