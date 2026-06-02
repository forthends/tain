"""EvaluationPlugin — 七维成熟度评估、可执行报告、投产判定."""

from __future__ import annotations
import json
import logging
from pathlib import Path
from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol
from tain_agent.plugins.evaluation.models import EvaluationSnapshot, EvaluationReport
from tain_agent.plugins.evaluation.engine import MaturityEngine
from tain_agent.plugins.evaluation.reporter import EvaluationReporter
from tain_agent.plugins.evaluation.gate import ProductionGate, ProductionStatus
from tain_agent.plugins.evaluation.triggers import TriggerManager

logger = logging.getLogger(__name__)


class EvaluationPlugin:
    """8th plugin — periodic seven-dimension maturity evaluation with executable reports."""

    def __init__(self, routine_interval: int = 50, deep_interval: int = 200):
        self._ctx: AgentContext | None = None
        self._engine: MaturityEngine | None = None
        self._reporter: EvaluationReporter | None = None
        self._gate: ProductionGate | None = None
        self._triggers: TriggerManager | None = None
        self._routine_interval = routine_interval
        self._deep_interval = deep_interval
        self._history: list[EvaluationSnapshot] = []
        self._evaluations_run: int = 0
        self._eval_dir: Path | None = None

    # ── PluginProtocol ───────────────────────────────────────────

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        self._eval_dir = ctx.workspace_path / "evaluations"
        self._eval_dir.mkdir(parents=True, exist_ok=True)
        (self._eval_dir / "snapshots").mkdir(exist_ok=True)
        (self._eval_dir / "reports").mkdir(exist_ok=True)
        self._engine = MaturityEngine()
        self._reporter = EvaluationReporter()
        self._gate = ProductionGate()
        self._triggers = TriggerManager(self._routine_interval, self._deep_interval)
        self._load_history()

    def shutdown(self) -> None:
        self._save_history()
        self._engine = None
        self._reporter = None
        self._gate = None

    def health_check(self) -> HealthStatus:
        return HealthStatus(
            status="ok",
            metrics={
                "evaluations_run": float(self._evaluations_run),
                "history_size": float(len(self._history)),
            },
        )

    def snapshot(self) -> dict:
        return {"evaluations_run": self._evaluations_run, "history_size": len(self._history)}

    def restore(self, data: dict) -> None:
        pass

    # ── PRAL hooks ───────────────────────────────────────────────

    def on_cycle_start(self, cycle: int) -> None:
        pass

    def on_cycle_end(self, cycle: int) -> None:
        if self._triggers is None:
            return
        self._triggers.on_cycle(cycle)
        trigger_state = self._triggers.consume()
        if trigger_state["routine"]:
            mode = "deep" if trigger_state["deep"] else "routine"
            self.evaluate(mode=mode)

    def enrich_prompt(self, base: str) -> str:
        latest = self.get_latest_snapshot()
        if latest is None:
            return base
        dims = latest.dimensions
        risks = [d for d in dims.values() if d.score < 0.5]
        if not risks:
            return base
        lines = [base, "", "## 评估系统反馈", "", "以下维度需要关注："]
        for r in risks:
            lines.append(f"- **{r.dimension}**: 成熟度 {r.score:.2f} ({r.level.name})")
            if r.recommendations:
                lines.append(f"  建议: {r.recommendations[0]}")
        return "\n".join(lines)

    def on_llm_response(self, response) -> None:
        pass

    # ── Evaluation API ───────────────────────────────────────────

    def evaluate(self, plugin_metrics: dict | None = None, mode: str = "routine") -> EvaluationReport | None:
        if self._engine is None or self._reporter is None:
            return None

        if plugin_metrics is None:
            plugin_metrics = self._collect_metrics()

        # Allow empty metrics to produce a baseline snapshot
        snap = self._engine.evaluate(self._ctx.agent_id, plugin_metrics)
        self._history.append(snap)
        self._evaluations_run += 1

        history_dicts = [{"agent_id": s.agent_id, "overall_score": s.overall_score,
                          "evaluated_at": s.evaluated_at} for s in self._history[-10:]]

        readiness = self._gate.evaluate(snap, self._history[-5:]) if self._gate else None

        report = self._reporter.generate(
            snap, agent_name=self._ctx.agent_name,
            history=history_dicts, readiness=readiness,
        )

        self._save_snapshot(snap)
        if mode == "deep":
            self._save_report(report)

        self._inject_action_items(report)
        return report

    def get_latest_snapshot(self) -> EvaluationSnapshot | None:
        return self._history[-1] if self._history else None

    def get_latest_report(self) -> EvaluationReport | None:
        snap = self.get_latest_snapshot()
        if snap is None or self._reporter is None:
            return None
        return self._reporter.generate(snap, agent_name=self._ctx.agent_name)

    def get_history(self, n: int = 10) -> list[EvaluationSnapshot]:
        return self._history[-n:]

    def get_production_readiness(self) -> dict:
        snap = self.get_latest_snapshot()
        if snap is None or self._gate is None:
            return {"status": "not_ready"}
        readiness = self._gate.evaluate(snap, self._history[-5:])
        return {"status": readiness.status.value, "stable_streak": readiness.stable_streak}

    # ── Internal ─────────────────────────────────────────────────

    def _collect_metrics(self) -> dict[str, dict]:
        # TODO: wire real plugin metric sources (memory, tool, workflow stats)
        return {}

    def _inject_action_items(self, report: EvaluationReport) -> None:
        for item in report.action_items[:3]:
            logger.info("Eval action item P%d [%s]: %s", item.priority, item.dimension, item.goal_title)

    def _save_snapshot(self, snap: EvaluationSnapshot) -> None:
        if self._eval_dir:
            import dataclasses
            fname = f"snapshot_{snap.evaluated_at.replace(':', '')}.json"
            (self._eval_dir / "snapshots" / fname).write_text(
                json.dumps(dataclasses.asdict(snap), ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )

    def _save_report(self, report: EvaluationReport) -> None:
        if self._eval_dir:
            md = self._reporter.render_markdown(report)
            fname = f"report_{report.evaluated_at.replace(':', '')}.md"
            (self._eval_dir / "reports" / fname).write_text(md, encoding="utf-8")

    def _load_history(self) -> None:
        if self._eval_dir:
            snap_dir = self._eval_dir / "snapshots"
            if snap_dir.exists():
                try:
                    for f in sorted(snap_dir.glob("*.json"))[-20:]:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        from tain_agent.plugins.evaluation.models import DimensionMaturity
                        dims = {}
                        for k, v in data.get("dimensions", {}).items():
                            dims[k] = DimensionMaturity(**v)
                        snap = EvaluationSnapshot(
                            agent_id=data.get("agent_id", ""),
                            dimensions=dims,
                            evaluated_at=data.get("evaluated_at", ""),
                            report_id=data.get("report_id", ""),
                        )
                        self._history.append(snap)
                except Exception:
                    pass

    def _save_history(self) -> None:
        pass
