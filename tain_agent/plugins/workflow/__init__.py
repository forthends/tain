"""WorkflowPlugin — DAG-based workflow management.

Manages workflows as state machines with topological execution ordering
and parallel step grouping. Workflows are persisted as JSON files.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol
from tain_agent.plugins.workflow.engine import (
    Workflow,
    WorkflowState,
    WorkflowStep,
    StepResult,
    StepType,
    RetryPolicy,
)

logger = logging.getLogger(__name__)


class WorkflowPlugin:
    """Plugin that owns workflow state machines for the agent.

    Workflows are DAG-based: steps have dependencies, execution follows
    topological order, and parallel groups identify steps that can run
    concurrently.

    Required PluginProtocol methods: initialize, shutdown, health_check,
    snapshot, restore.
    Optional PRAL hooks: on_cycle_start, on_cycle_end, enrich_prompt,
    on_llm_response.
    """

    version = "1.0.0"

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._workflows: dict[str, Workflow] = {}
        self._persist_dir: Path | None = None

    # ── PluginProtocol ──────────────────────────────────────────────

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        self._persist_dir = ctx.workspace_path / "workflows"
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._load()

    def shutdown(self) -> None:
        self._save_all()
        self._workflows.clear()
        self._ctx = None

    def health_check(self) -> HealthStatus:
        if self._ctx is None:
            return HealthStatus(status="critical", alerts=["not initialized"])
        running = sum(
            1 for w in self._workflows.values() if w.state == WorkflowState.RUNNING
        )
        failed = sum(
            1 for w in self._workflows.values() if w.state == WorkflowState.FAILED
        )
        metrics = {
            "workflow_count": float(len(self._workflows)),
            "running": float(running),
            "failed": float(failed),
        }
        status = "warning" if failed > 0 else "ok"
        alerts = [f"{failed} workflow(s) failed"] if failed > 0 else []
        return HealthStatus(status=status, metrics=metrics, alerts=alerts)

    def snapshot(self) -> dict[str, Any]:
        return {
            name: {
                "name": w.name,
                "description": w.description,
                "state": w.state.value,
                "step_count": len(w.steps),
                "context": dict(w.context),
            }
            for name, w in self._workflows.items()
        }

    def restore(self, data: dict[str, Any]) -> None:
        # Workflows reload from disk on initialize
        pass

    # ── PRAL hooks ──────────────────────────────────────────────────

    def on_cycle_start(self, cycle: int) -> None:
        pass

    def on_cycle_end(self, cycle: int) -> None:
        self._save_all()

    def enrich_prompt(self, base: str) -> str:
        active = [
            w for w in self._workflows.values()
            if w.state in (WorkflowState.RUNNING, WorkflowState.PENDING)
        ]
        if not active:
            return base

        parts = [base, "", "## 活跃工作流 (Active Workflows)"]
        for w in active[:5]:
            parts.append(f"- **{w.name}** [{w.state.value}] — {w.description[:80]}")
        return "\n".join(parts)

    def on_llm_response(self, response: Any) -> None:
        pass

    # ── Persistence ─────────────────────────────────────────────────

    def _save_all(self) -> None:
        if self._persist_dir is None:
            return
        for name, wf in self._workflows.items():
            self._save_one(name, wf)

    def _save_one(self, name: str, wf: Workflow) -> None:
        if self._persist_dir is None:
            return
        try:
            path = self._persist_dir / f"{name}.json"
            import dataclasses
            data = dataclasses.asdict(wf)
            data["state"] = wf.state.value
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save workflow '%s': %s", name, e)

    def _load(self) -> None:
        if self._persist_dir is None or not self._persist_dir.exists():
            return
        for path in self._persist_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                name = data.pop("name", path.stem)
                state_val = data.pop("state", "pending")
                steps_data = data.pop("steps", [])
                step_results_data = data.pop("step_results", {})

                steps = [
                    WorkflowStep(
                        name=s.get("name", ""),
                        description=s.get("description", ""),
                        step_type=StepType(s.get("step_type", "tool")),
                        tool=s.get("tool", ""),
                        prompt=s.get("prompt", ""),
                        depends_on=s.get("depends_on", []),
                        retry=RetryPolicy(**s.get("retry", {})),
                        timeout_seconds=s.get("timeout_seconds", 300.0),
                        properties=s.get("properties", {}),
                    )
                    for s in steps_data
                ]

                wf = Workflow(
                    name=name,
                    description=data.get("description", ""),
                    steps=steps,
                    state=WorkflowState(state_val),
                    context=data.get("context", {}),
                    step_results=step_results_data,
                    created_at=data.get("created_at", ""),
                    updated_at=data.get("updated_at", ""),
                )
                self._workflows[name] = wf
            except Exception as e:
                logger.warning("Failed to load workflow '%s': %s", path, e)

    # ── Workflow API ────────────────────────────────────────────────

    def create(
        self,
        name: str,
        description: str,
        steps: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> Workflow:
        """Create a new workflow and validate it.

        Args:
            name: Unique workflow name.
            description: Human-readable description.
            steps: List of step dicts with keys: name, description, step_type,
                   tool, prompt, depends_on, timeout_seconds.
            context: Optional initial context dict.

        Returns the created Workflow.

        Raises ValueError if validation fails.
        """
        wf_steps: list[WorkflowStep] = []
        for s in steps:
            wf_steps.append(WorkflowStep(
                name=s["name"],
                description=s.get("description", ""),
                step_type=StepType(s.get("step_type", "tool")),
                tool=s.get("tool", ""),
                prompt=s.get("prompt", ""),
                depends_on=s.get("depends_on", []),
                timeout_seconds=s.get("timeout_seconds", 300.0),
                properties=s.get("properties", {}),
            ))

        wf = Workflow(
            name=name,
            description=description,
            steps=wf_steps,
            context=context or {},
        )

        # Validate
        errors = wf.validate()
        if errors:
            raise ValueError(f"Workflow validation failed: {'; '.join(errors)}")

        self._workflows[name] = wf
        self._save_one(name, wf)
        return wf

    def start(self, name: str) -> Workflow | None:
        """Start a workflow (PENDING → RUNNING)."""
        wf = self._workflows.get(name)
        if wf is None or wf.state != WorkflowState.PENDING:
            return None
        wf.state = WorkflowState.RUNNING
        wf.updated_at = datetime.now(timezone.utc).isoformat()
        self._save_one(name, wf)
        return wf

    def pause(self, name: str) -> Workflow | None:
        """Pause a running workflow (RUNNING → PAUSED)."""
        wf = self._workflows.get(name)
        if wf is None or wf.state != WorkflowState.RUNNING:
            return None
        wf.state = WorkflowState.PAUSED
        wf.updated_at = datetime.now(timezone.utc).isoformat()
        self._save_one(name, wf)
        return wf

    def resume(self, name: str) -> Workflow | None:
        """Resume a paused workflow (PAUSED → RUNNING)."""
        wf = self._workflows.get(name)
        if wf is None or wf.state != WorkflowState.PAUSED:
            return None
        wf.state = WorkflowState.RUNNING
        wf.updated_at = datetime.now(timezone.utc).isoformat()
        self._save_one(name, wf)
        return wf

    def status(self, name: str) -> dict[str, Any] | None:
        """Get detailed status of a workflow."""
        wf = self._workflows.get(name)
        if wf is None:
            return None
        topo = wf.topological_order()
        groups = wf.parallel_groups()
        return {
            "name": wf.name,
            "description": wf.description,
            "state": wf.state.value,
            "steps": len(wf.steps),
            "topological_order": topo,
            "parallel_groups": groups,
            "context_keys": list(wf.context.keys()),
            "created_at": wf.created_at,
            "updated_at": wf.updated_at,
        }

    def status_all(self) -> list[dict[str, Any]]:
        """Get status of all workflows."""
        results = []
        for name in self._workflows:
            s = self.status(name)
            if s:
                results.append(s)
        return results

    def advance(self, step_result: StepResult) -> bool:
        """Record a step result for the workflow.

        Returns True if the result was recorded, False if the workflow
        doesn't exist.
        """
        # Find the workflow by scanning for this step name
        for wf in self._workflows.values():
            if any(s.name == step_result.step_name for s in wf.steps):
                if step_result.step_name not in wf.step_results:
                    wf.step_results[step_result.step_name] = []
                wf.step_results[step_result.step_name].append(step_result)

                # Check if all steps have at least one result → mark COMPLETED
                all_done = all(
                    s.name in wf.step_results and len(wf.step_results[s.name]) > 0
                    for s in wf.steps
                )
                if all_done:
                    wf.state = WorkflowState.COMPLETED

                # Mark FAILED if any step result is a failure with no retries left
                for step in wf.steps:
                    if step.name in wf.step_results:
                        results = wf.step_results[step.name]
                        if results and not results[-1].success:
                            retry_count = results[-1].retry_count
                            if retry_count >= step.retry.max_retries:
                                wf.state = WorkflowState.FAILED
                                break

                wf.updated_at = datetime.now(timezone.utc).isoformat()
                self._save_one(wf.name, wf)
                return True
        return False

    def plan_from_goal(
        self,
        goal_title: str,
        llm_backend: Any = None,
    ) -> Workflow:
        """Create a workflow from a high-level goal description.

        If an llm_backend is provided, uses it to decompose the goal into
        steps. Otherwise creates a simple single-step workflow.

        Args:
            goal_title: The goal to decompose into a workflow.
            llm_backend: Optional callable llm_backend(prompt) -> str.

        Returns the created Workflow.
        """
        if llm_backend is not None:
            try:
                prompt = (
                    f"Decompose this goal into workflow steps: {goal_title}\n"
                    "Return a JSON list of steps, each with: name, description, "
                    "step_type (tool/llm/human), depends_on (list of step names). "
                    "Output only valid JSON."
                )
                response = llm_backend(prompt)
                import json as _json
                steps_data = _json.loads(response)
            except Exception as e:
                logger.warning("LLM planning failed: %s — using single step", e)
                steps_data = [{
                    "name": "execute",
                    "description": goal_title,
                    "step_type": "tool",
                    "tool": "",
                }]
        else:
            steps_data = [{
                "name": "execute",
                "description": goal_title,
                "step_type": "tool",
                "tool": "",
            }]

        return self.create(
            name=f"goal_{goal_title[:30].replace(' ', '_')}",
            description=f"Workflow for goal: {goal_title}",
            steps=steps_data,
            context={"goal_title": goal_title},
        )
