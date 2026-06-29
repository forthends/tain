"""
AutonomousEvolutionLoop — closed 8-stage evolution cycle.

Replaces ImprovementLoop with a stricter, more observable evolution pipeline:

    GAP_DETECT → SPEC_DESIGN → CODE_GENERATE → CONTRACT_CHECK
         → SANDBOX_FORGE → REGISTER → ONLINE_VERIFY → EVALUATE

Key properties:
  - Rate-limited: minimum interval between evolution cycles
  - Contract-enforced: every generated tool must pass BehaviorContract checks
  - Reversible: forged tools are rolled back on failure
  - Observable: CycleResult captures every stage outcome
  - Quota-enforced: max improvements per session
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from tain_agent.core.time_utils import now
from tain_agent.evolution.behavior_contract import (
    BehaviorContract,
    ContractValidationError,
)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from tain_agent.plugins.tool.forge_cycle import ImprovementSpec

logger = logging.getLogger(__name__)

# ── System prompt for code generation ────────────────────────────────────────

CODE_GENERATION_SYSTEM_PROMPT = (
    "You are a Python code generator for an AI agent framework. "
    "Generate a single Python function that implements the requested tool capability. "
    "\n\n"
    "Requirements:\n"
    "- Return ONLY the function definition (with docstring).\n"
    "- All parameters must have type annotations and default values.\n"
    "- Return a dictionary (dict) with at least a 'result' or 'success' key.\n"
    "- Use ONLY modules from the provided sandbox allowlist.\n"
    "- Do NOT perform file I/O, network calls, or subprocess execution unless explicitly allowed.\n"
    "- Keep the function under 100 lines.\n"
    "\n"
    "Output format:\n"
    "```python\n"
    "def function_name(param: type = default) -> dict:\n"
    '    """Docstring."""\n'
    "    ...\n"
    "```\n\n"
    "```contract\n"
    '{"side_effects": ["none"], "max_runtime_ms": 1000}\n'
    "```\n"
    "\n"
    "The contract JSON declares the tool's side effects and maximum runtime. "
    "Valid side effects: 'none', 'file_read', 'file_write', 'network', 'subprocess'. "
    "When unsure, use 'none' for pure-compute tools."
)


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class CycleResult:
    """Result of a single evolution cycle (8 stages)."""

    success: bool
    skipped: bool = False
    stage: str = ""
    spec: ImprovementSpec | None = None
    code: str | None = None
    contract: BehaviorContract | None = None
    error: str = ""
    details: dict = field(default_factory=dict)

    @classmethod
    def skipped_result(cls, assessment: dict) -> "CycleResult":
        """Create a skipped-cycle result from an assessment."""
        return cls(
            success=False,
            skipped=True,
            stage="GAP_DETECT",
            error=f"need_score {assessment.get('need_score', 0)} below threshold",
            details={"assessment": assessment},
        )

    @classmethod
    def failed(
        cls,
        stage: str,
        spec: ImprovementSpec | None = None,
        error: str = "",
        **details,
    ) -> "CycleResult":
        """Create a failure result at a specific stage."""
        return cls(
            success=False,
            stage=stage,
            spec=spec,
            error=error,
            details=details,
        )

    @classmethod
    def success_result(
        cls,
        spec: ImprovementSpec,
        code: str,
        contract: BehaviorContract,
        **details,
    ) -> "CycleResult":
        """Create a success result."""
        return cls(
            success=True,
            stage="EVALUATE",
            spec=spec,
            code=code,
            contract=contract,
            details=details,
        )


@dataclass
class ToolSnapshot:
    """Snapshot of tool state captured before/after an evolution cycle."""

    tool_name: str
    code: str | None
    tool_list_snapshot: dict
    forged_list_snapshot: dict
    knowledge_node_count: int = 0
    captured_at: str = ""


@dataclass
class QualityDelta:
    """Difference between before and after quality snapshots."""

    degraded: bool = False
    reason: str = ""


@dataclass
class _VerifyResult:
    """Result of online tool verification (consecutive calls)."""

    consecutive_failures: int = 0


# ── AutonomousEvolutionLoop ──────────────────────────────────────────────────

class AutonomousEvolutionLoop:
    """Closed 8-stage evolution cycle: GAP_DETECT → SPEC_DESIGN → CODE_GENERATE
    → CONTRACT_CHECK → SANDBOX_FORGE → REGISTER → ONLINE_VERIFY → EVALUATE.
    """

    # INI file for state persistence
    _STATE_FILE = "evolution_loop.json"

    def __init__(
        self,
        llm_backend,           # LLMBackend with create_message()
        tool_plugin,           # ToolPlugin instance
        knowledge_plugin,      # KnowledgePlugin instance
        lineage,               # LineageTracker instance
        agent_name,            # agent name for state directory isolation
    ):
        self._llm = llm_backend
        self._tools = tool_plugin
        self._knowledge = knowledge_plugin
        self._lineage = lineage
        self._agent_name = agent_name

        # ── State directory (defaults to temp to avoid CWD pollution) ──
        import tempfile
        self._STATE_DIR = (
            Path(tempfile.gettempdir()) / "tain-agent" / agent_name / "state"
        )

        # ── Config (overridable via configure()) ──
        self.min_interval_seconds = 300
        self.max_improvements_per_session = 10
        self.max_generate_retries = 3
        self.rollback_on_failure_count = 3
        self.contract_enforcement = "strict"  # strict | warn | off

        # ── Runtime state ──
        self._lock = threading.Lock()
        self._running = False
        self._paused = False
        self._improvements_this_session = 0
        self._last_cycle_at: Optional[str] = None
        self._cycle_history: list[dict] = []
        self._thread: Optional[threading.Thread] = None
        self._snapshots: dict[str, ToolSnapshot] = {}

        # ── Trigger config (4 real-signal dimensions) ──
        self.trigger_config = {
            "min_trigger_score": 0.3,
            "capability_gap":   {"enabled": True, "threshold": 0.0,  "weight": 0.30},
            "tool_dedup":       {"enabled": True, "threshold": 0.40, "weight": 0.10},
            "task_completion":  {"enabled": True, "threshold": 0.20, "weight": 0.35},
            "goal_achievement": {"enabled": True, "threshold": 0.30, "weight": 0.25},
        }
        self._last_trigger_scores: dict = {}
        self._last_triggered_by: list = []
        self._load_state()

        # _generate_spec counter for unique function names
        self._spec_counter: dict[str, int] = {}

    # ── Public API ───────────────────────────────────────────────────────

    def configure(self, **kwargs) -> None:
        """Apply config overrides from config.yaml evolution section."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        # Handle trigger_config updates
        if "trigger_config" in kwargs:
            tc = kwargs["trigger_config"]
            if isinstance(tc, dict):
                if "min_trigger_score" in tc:
                    self.trigger_config["min_trigger_score"] = tc["min_trigger_score"]
                for dim in self.trigger_config:
                    if dim in tc and isinstance(tc[dim], dict):
                        self.trigger_config[dim].update(tc[dim])

    def start(self) -> dict:
        """Start background evolution thread. Returns state."""
        with self._lock:
            if self._running:
                return {"success": False, "error": "Loop is already active.", "running": True}

            self._running = True
            self._paused = False
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            logger.info("AutonomousEvolutionLoop started (background thread).")
            return {"success": True, "running": True, "paused": False}

    def stop(self) -> dict:
        """Stop the evolution loop. Returns state."""
        with self._lock:
            was_running = self._running
            self._running = False
            self._paused = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        with self._lock:
            self._thread = None
        if was_running:
            self._save_state()
        logger.info("AutonomousEvolutionLoop stopped.")
        return {"success": True, "running": False, "paused": False}

    def pause(self) -> dict:
        """Pause the evolution loop. Returns state."""
        with self._lock:
            self._paused = True
            return {"success": True, "running": self._running, "paused": True}

    def resume(self) -> dict:
        """Resume a paused evolution loop. Returns state."""
        with self._lock:
            self._paused = False
            return {"success": True, "running": self._running, "paused": False}

    def run_one_cycle(self) -> CycleResult:
        """Execute the full 8-stage evolution cycle synchronously.

        Returns:
            CycleResult with success/skip/failure and stage details.
        """
        # Update timestamp on every cycle (even skipped/failed) for rate-limiting
        self._last_cycle_at = now().isoformat()

        # Stage 1: GAP_DETECT
        assessment = self._assess_need()
        if not assessment.get("should_trigger", False):
            return CycleResult.skipped_result(assessment)

        # Stage 2: SPEC_DESIGN
        spec = self._generate_spec(assessment)
        if spec is None:
            return CycleResult.failed(
                "SPEC_DESIGN", error="Could not generate improvement spec."
            )

        # Stage 3: CODE_GENERATE (with retry loop)
        code, contract = self._generate_code_with_retry(spec)
        if code is None:
            return CycleResult.failed(
                "CODE_GENERATE", spec=spec,
                error=f"Code generation failed after {self.max_generate_retries} retries.",
            )
        if contract is None:
            return CycleResult.failed(
                "CODE_GENERATE", spec=spec,
                error="Contract parsing failed.",
            )

        # Stage 4: CONTRACT_CHECK (only for non-strict modes;
        # in strict mode the contract is already verified inside _generate_code_with_retry)
        if self.contract_enforcement != "strict":
            if not self._check_contract(code, contract):
                return CycleResult.failed(
                    "CONTRACT_CHECK", spec=spec,
                    error="Generated code violates its declared contract.",
                    code=code, contract=contract,
                )

        # Stage 5: SANDBOX_FORGE
        forge_result = self._forge_tool(spec, code)
        if not forge_result.get("success", False):
            return CycleResult.failed(
                "SANDBOX_FORGE", spec=spec, code=code,
                error=forge_result.get("error", "Forge failed."),
            )

        # Stage 6: REGISTER — verify tool appeared
        tools = self._tools.list_tools()
        if spec.function_name not in tools:
            return CycleResult.failed(
                "REGISTER", spec=spec, code=code,
                error=f"Tool '{spec.function_name}' not found in registry after forging.",
            )

        # Stage 7: ONLINE_VERIFY
        verify_result = self._verify_online(spec.function_name)
        if verify_result.consecutive_failures >= self.rollback_on_failure_count:
            self._rollback(spec.function_name, self._snapshots.get(spec.function_name))
            return CycleResult.failed(
                "ONLINE_VERIFY", spec=spec, code=code,
                error=f"Tool failed {verify_result.consecutive_failures} consecutive "
                      f"online verifications. Rolled back.",
            )

        # Stage 8: EVALUATE
        before_snapshot = self._snapshots.get(spec.function_name)
        if before_snapshot:
            delta = self._evaluate_quality_delta(before_snapshot)
            if delta.degraded:
                self._rollback(spec.function_name, before_snapshot)
                return CycleResult.failed(
                    "EVALUATE", spec=spec, code=code, contract=contract,
                    error=f"Quality degraded: {delta.reason}. Rolled back.",
                )

        # Record success
        with self._lock:
            self._save_snapshot(spec.function_name, code)
            self._improvements_this_session += 1

        # Record in lineage
        try:
            self._lineage.record_forge(
                tool_name=spec.function_name,
                tool_code=code,
                agent_version="0.10.0",
                reasoning=spec.reasoning,
            )
        except Exception:
            logger.debug("Lineage recording skipped.", exc_info=True)

        return CycleResult.success_result(spec, code, contract)

    def export_state(self) -> dict:
        """Return state dict for evolution_metrics.py compatibility."""
        with self._lock:
            return {
                "running": self._running,
                "paused": self._paused,
                "improvements_this_session": self._improvements_this_session,
                "max_improvements_per_session": self.max_improvements_per_session,
                "last_cycle_at": self._last_cycle_at,
                "cycle_history": list(self._cycle_history),
                "trigger_config": dict(self.trigger_config),
                "last_trigger_scores": dict(self._last_trigger_scores),
                "last_triggered_by": list(self._last_triggered_by),
                "contract_enforcement": self.contract_enforcement,
            }

    def execute_once_if_needed(self) -> dict:
        """Compatibility shim for cognitive_loop.py call pattern.

        Assesses need and executes one cycle only if triggered.

        Returns:
            dict with 'triggered' (bool) and optional 'result' (CycleResult).
        """
        assessment = self._assess_need()

        if not assessment.get("should_trigger", False):
            return {
                "triggered": False,
                "assessment": assessment,
                "reason": (
                    f"need_score {assessment.get('need_score', 0)} "
                    f"< threshold"
                ),
            }

        # Quota check
        if self._improvements_this_session >= self.max_improvements_per_session:
            return {
                "triggered": False,
                "assessment": assessment,
                "reason": "Quota exhausted (max_improvements_per_session).",
            }

        # Interval check
        if self._last_cycle_at:
            try:
                last_time = datetime.fromisoformat(self._last_cycle_at)
                elapsed = (now() - last_time).total_seconds()
                if elapsed < self.min_interval_seconds:
                    return {
                        "triggered": False,
                        "assessment": assessment,
                        "reason": f"Interval not elapsed ({elapsed:.0f}s < {self.min_interval_seconds}s).",
                    }
            except (ValueError, TypeError):
                pass

        result = self.run_one_cycle()
        return {
            "triggered": True,
            "assessment": assessment,
            "result": result,
        }

    # ── Stage 1: Gap Detection ───────────────────────────────────────────

    def _assess_need(self) -> dict:
        """Evaluate 4 trigger dimensions and compute a weighted need score.

        Returns:
            dict with 'should_trigger', 'scores', 'triggered_by', 'need_score'.
        """
        dims = [
            ("capability_gap",   self._eval_capability_gap),
            ("tool_dedup",       self._eval_tool_dedup),
            ("task_completion",  self._eval_task_completion),
            ("goal_achievement", self._eval_goal_achievement),
        ]

        scores: dict[str, float] = {}
        triggered_by: list[dict] = []
        weighted_sum = 0.0
        total_weight = 0.0

        for dim_name, evaluator in dims:
            cfg = self.trigger_config.get(dim_name, {})
            if not cfg.get("enabled", True):
                scores[dim_name] = 0.0
                continue

            threshold = cfg.get("threshold", 0.3)
            weight = cfg.get("weight", 0.1)

            try:
                score = evaluator()
            except Exception:
                logger.debug(
                    "Dimension evaluator '%s' failed — defaulting to 0.0",
                    dim_name, exc_info=True,
                )
                score = 0.0

            scores[dim_name] = score
            weighted_sum += score * weight
            total_weight += weight

            if score > threshold:
                triggered_by.append({"dimension": dim_name, "score": score})

        need_score = weighted_sum / max(total_weight, 0.001)
        min_trigger = self.trigger_config.get("min_trigger_score", 0.01)

        should_trigger = need_score >= min_trigger

        self._last_trigger_scores = dict(scores)
        self._last_triggered_by = list(triggered_by)

        return {
            "should_trigger": should_trigger,
            "scores": scores,
            "triggered_by": triggered_by,
            "need_score": round(need_score, 4),
        }

    # ── Dimension evaluators ─────────────────────────────────────────────

    def _eval_capability_gap(self) -> float:
        """Score based on goals requiring capabilities not in current toolset."""
        try:
            tools = self._tools.list_tools()
            tool_names = set(tools.keys())
        except Exception:
            return 0.0

        try:
            active_goals = self._knowledge.goals.list_active()
        except Exception:
            active_goals = []

        if not active_goals:
            # Fallback: mild tool-count signal
            count = len(tool_names)
            if count < 3:
                return round((3 - count) / 3, 4)
            return 0.0

        gap_count = 0
        for goal_dict in active_goals:
            required = goal_dict.get("required_capability", "")
            if required and required not in tool_names:
                gap_count += 1

        if gap_count == 0:
            return 0.0
        return round(gap_count / len(active_goals), 4)

    def _eval_tool_dedup(self) -> float:
        """Hash-based dedup check on forged tools. Returns dedup score 0-1."""
        try:
            forged = self._tools.list_forged()
            if not forged:
                return 0.0

            # Build hashes for each tool code to detect near-duplicates
            code_hashes = set()
            for tool_name, code in forged.items():
                if isinstance(code, str):
                    h = hashlib.sha256(code.encode()).hexdigest()[:12]
                    code_hashes.add(h)

            n_forged = len(forged)
            n_unique = len(code_hashes)

            if n_forged == 0:
                return 0.0

            # dedup_score: 1 means all unique (good), 0 means all duplicates (bad)
            dedup_ratio = n_unique / n_forged

            # Higher dedup score = more need for improvement (more duplicates)
            return round(1.0 - dedup_ratio, 4)
        except Exception:
            logger.debug("tool_dedup evaluation failed — score: 0.0", exc_info=True)
            return 0.0

    def _eval_task_completion(self) -> float:
        """Score based on recent tool-call failure rate.

        Reads tool_result_log from KnowledgePlugin's dynamic layer.
        High failure rate → high evolution need.
        """
        try:
            if not hasattr(self._knowledge, '_dynamic'):
                return 0.0
            log_entries = [
                e for e in self._knowledge._dynamic
                if isinstance(e, dict) and e.get("type") == "tool_result"
            ]
            if not log_entries:
                return 0.0
            recent = log_entries[-20:]  # last 20 tool results
            failures = sum(
                1 for e in recent
                if not e.get("success", False)
            )
            return round(failures / len(recent), 4)
        except Exception:
            return 0.0

    def _eval_goal_achievement(self) -> float:
        """Query knowledge_plugin for goal achievement rate."""
        try:
            if hasattr(self._knowledge, "goals"):
                goals = self._knowledge.goals
                if not goals:
                    return 0.0
                # Count completed goals
                completed = sum(
                    1 for g in goals
                    if (isinstance(g, dict) and g.get("status") == "completed")
                    or (hasattr(g, "status") and getattr(g, "status", "") == "completed")
                )
                if len(goals) == 0:
                    return 0.0
                # Higher score = more uncompleted goals (need for improvement)
                return round(1.0 - (completed / len(goals)), 4)
        except Exception:
            logger.debug("goal_achievement evaluation failed — score: 0.0", exc_info=True)
        return 0.0

    # ── Stage 2: Spec Generation ─────────────────────────────────────────

    def _generate_spec(self, assessment: dict) -> ImprovementSpec | None:
        """Generate an ImprovementSpec enriched with goal and failure context."""
        triggered_by = assessment.get("triggered_by", [])
        scores = assessment.get("scores", {})

        if not triggered_by:
            if scores:
                best_dim = max(scores, key=lambda k: scores.get(k, 0.0))
                triggered_by = [{"dimension": best_dim, "score": scores[best_dim]}]
            else:
                triggered_by = [{"dimension": "capability_gap", "score": 0.5}]

        primary = triggered_by[0]
        dim_name = primary["dimension"]

        # ── Query goals for context ──
        active_goals: list[dict] = []
        try:
            if hasattr(self._knowledge, 'goals'):
                active_goals = self._knowledge.goals.list_active()
        except Exception:
            pass

        # ── Query recent tool failures for context ──
        recent_failures: list[dict] = []
        try:
            dynamic = getattr(self._knowledge, '_dynamic', [])
            recent_failures = [
                e for e in dynamic[-30:]
                if isinstance(e, dict) and e.get("type") == "tool_result"
                and not e.get("success", False)
            ][-5:]  # last 5 failures
        except Exception:
            pass

        # ── Build function name from goal context if available ──
        function_name = ""
        if active_goals:
            # Pick the first active goal with a required_capability
            for g in active_goals:
                cap = g.get("required_capability", "")
                if cap:
                    function_name = cap
                    break
        if not function_name:
            counter_key = f"auto_{dim_name}"
            idx = self._spec_counter.get(counter_key, 0) + 1
            self._spec_counter[counter_key] = idx
            function_name = f"auto_{dim_name}" if idx == 1 else f"auto_{dim_name}_{idx}"

        # ── Build capability_id ──
        ts = now().strftime("%Y%m%d%H%M%S")
        capability_id = f"{function_name}_{ts}"

        # ── Build description from goal context ──
        if active_goals:
            goal_descriptions = [
                g["description"] for g in active_goals[:2]
                if g.get("description")
            ]
            if goal_descriptions:
                description = (
                    f"Support active goals: {'; '.join(goal_descriptions)}"
                )
                if len(active_goals) > 2:
                    description += f" (and {len(active_goals) - 2} more)"
            else:
                description = f"Address evolution dimension: {dim_name}"
        else:
            dim_descriptions = {
                "capability_gap": "Fill capability gap",
                "tool_dedup": "Deduplicate tools",
                "task_completion": "Improve task completion",
                "goal_achievement": "Advance goal achievement",
            }
            description = dim_descriptions.get(dim_name, f"Address evolution dimension: {dim_name}")

        if len(triggered_by) > 1:
            others = [t["dimension"] for t in triggered_by[1:3]]
            description += f" (also: {', '.join(others)})"

        # ── Build reasoning with failure context ──
        reasoning_parts = []
        for t in triggered_by[:3]:
            reasoning_parts.append(f"{t['dimension']}: {t['score']:.3f}")

        if recent_failures:
            fail_names = set(f.get("tool_name", "unknown") for f in recent_failures)
            reasoning_parts.append(
                f"Recent failures ({len(recent_failures)}): {', '.join(sorted(fail_names))}"
            )

        reasoning = "Triggered by: " + "; ".join(reasoning_parts)

        from tain_agent.plugins.tool.forge_cycle import ImprovementSpec as _ISpec
        return _ISpec(
            capability_id=capability_id,
            description=description,
            function_name=function_name,
            parameters={},
            reasoning=reasoning,
        )

    # ── Stage 3: Code Generation ─────────────────────────────────────────

    def _generate_code_with_retry(
        self, spec: ImprovementSpec
    ) -> tuple[str | None, BehaviorContract | None]:
        """Generate code with retry loop for contract enforcement.

        In strict mode, retries up to max_generate_retries if contract check fails.
        """
        last_code: str | None = None
        last_contract: BehaviorContract | None = None

        for attempt in range(1, self.max_generate_retries + 1):
            code, contract = self._generate_code(spec, retry=(attempt > 1))
            if code is None or contract is None:
                continue

            last_code = code
            last_contract = contract

            # In strict mode, verify contract compliance before returning
            if self.contract_enforcement == "strict":
                if self._check_contract(code, contract):
                    return code, contract
                logger.debug(
                    "Contract check failed for '%s' (attempt %d/%d).",
                    spec.function_name, attempt, self.max_generate_retries,
                )
                continue

            return code, contract

        # In strict mode, if all retries exhausted without passing contract check,
        # return failure (None, None) — do NOT return unverified code.
        if self.contract_enforcement == "strict":
            logger.warning(
                "Contract check failed for '%s' after %d attempts. "
                "Returning failure to prevent unverified code execution.",
                spec.function_name, self.max_generate_retries,
            )
            return None, None

        return last_code, last_contract

    def _generate_code(
        self, spec: ImprovementSpec, retry: bool = False
    ) -> tuple[str | None, BehaviorContract | None]:
        """Call LLM backend to generate code + contract for the given spec.

        Returns:
            Tuple of (code, BehaviorContract) or (None, None) on failure.
        """
        prompt = self._build_generation_prompt(spec, retry=retry)

        try:
            response = self._llm.create_message(
                system_prompt=CODE_GENERATION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = response.text_blocks[0] if response.text_blocks else ""
        except Exception as exc:
            logger.error("LLM code generation failed: %s", exc)
            return None, None

        if not raw_text:
            return None, None

        code, contract_json = self._parse_generated_response(raw_text)
        if code is None:
            return None, None

        contract = self._build_contract(spec.function_name, contract_json)
        return code, contract

    def _build_generation_prompt(self, spec: ImprovementSpec, retry: bool = False) -> str:
        """Build the generation prompt with spec, sandbox allowlist, existing tools,
        active goal context, and failure examples."""
        try:
            allowlist = self._tools.get_sandbox_allowlist()
        except Exception:
            allowlist = ["json", "math", "datetime", "collections", "typing", "hashlib", "re"]

        try:
            existing_tools = self._tools.list_tools()
            tool_names = sorted(existing_tools.keys())[:20]
        except Exception:
            tool_names = []

        # ── Gather active goals for context ──
        active_goals: list[dict] = []
        try:
            if hasattr(self._knowledge, 'goals'):
                active_goals = self._knowledge.goals.list_active()
        except Exception:
            pass

        # ── Gather recent failures ──
        recent_failures: list[dict] = []
        try:
            dynamic = getattr(self._knowledge, '_dynamic', [])
            recent_failures = [
                e for e in dynamic[-30:]
                if isinstance(e, dict) and e.get("type") == "tool_result"
                and not e.get("success", False)
            ][-3:]
        except Exception:
            pass

        lines = [
            f"Task: Generate a Python function for the following improvement specification.",
            "",
            f"Function name: {spec.function_name}",
            f"Description: {spec.description}",
            f"Capability ID: {spec.capability_id}",
            f"Reasoning: {spec.reasoning}",
            "",
        ]

        if active_goals:
            lines.append("Active goals this tool should help accomplish:")
            for g in active_goals[:3]:
                lines.append(
                    f"  - [{g.get('status', 'active')}] {g.get('description', '')}"
                    f"{' (needs: ' + g.get('required_capability', '') + ')' if g.get('required_capability') else ''}"
                )
            lines.append("")

        if recent_failures:
            lines.append("Recent tool failures to address:")
            for f in recent_failures:
                lines.append(
                    f"  - {f.get('tool_name', 'unknown')} failed"
                    f" at {f.get('timestamp', 'unknown')}"
                )
            lines.append("")

        lines.extend([
            "Allowed modules (sandbox allowlist):",
            ", ".join(sorted(allowlist)),
            "",
        ])

        if tool_names:
            lines.append("Existing tools (for reference, avoid name collisions):")
            for name in tool_names:
                lines.append(f"  - {name}")
            lines.append("")

        if retry:
            lines.append(
                "NOTE: Previous attempt failed. Please ensure the function name "
                "matches EXACTLY and the contract is valid."
            )
            lines.append("")

        lines.extend([
            "Output format (MUST follow exactly):",
            "```python",
            f"def {spec.function_name}(...) -> dict:",
            '    """Docstring."""',
            "    # implementation",
            "    return {'result': ...}",
            "```",
            "",
            "```contract",
            '{"side_effects": ["none"], "max_runtime_ms": 1000}',
            "```",
            "",
            "Generate now:",
        ])

        return "\n".join(lines)

    def _parse_generated_response(self, raw_text: str) -> tuple[str | None, dict]:
        """Extract code and contract JSON from LLM response.

        Handles:
        - Markdown-fenced output: ```python ... ``` + ```contract ... ```
        - Bare output without fences
        """
        code: str | None = None
        contract_json: dict = {}

        text = raw_text.strip()

        # ── Try markdown-fenced extraction ──

        # Extract python code block
        py_pattern = r"```(?:python|py)\s*\n(.*?)```"
        py_matches = re.findall(py_pattern, text, re.DOTALL)
        if py_matches:
            code = py_matches[0].strip()

        # Extract contract block
        contract_pattern = r"```(?:contract|json)\s*\n(.*?)```"
        contract_matches = re.findall(contract_pattern, text, re.DOTALL)
        if contract_matches:
            try:
                contract_json = json.loads(contract_matches[0].strip())
            except json.JSONDecodeError:
                contract_json = {}

        # ── Fallback: bare text extraction ──

        if code is None:
            # Look for a function definition as the code block
            # Match: def name(params): body (indented lines)
            def_match = re.search(
                r"(def\s+\w+\s*\(.*?\)\s*->\s*\w+\s*:.*?(?:\n(?:    |\t)\S.*)*)",
                raw_text, re.DOTALL,
            )
            if not def_match:
                # Try without return type annotation
                def_match = re.search(
                    r"(def\s+\w+\s*\(.*?\)\s*:.*?(?:\n(?:    |\t)\S.*)*)",
                    raw_text, re.DOTALL,
                )
            if def_match:
                code = def_match.group(1).strip()

        if not contract_json and code is not None:
            # Try to find a bare JSON object after the function
            # Look for JSON after the last line of code
            json_match = re.search(
                r'\n\s*(\{[^{}]*"side_effects"[^{}]*\})', raw_text, re.DOTALL
            )
            if json_match:
                try:
                    contract_json = json.loads(json_match.group(1).strip())
                except json.JSONDecodeError:
                    pass

        # ── Final fallback: try parsing whole text as JSON ──
        if not contract_json:
            try:
                # Try to find any JSON object in the text
                json_match = re.search(r'\{[^{}]*\}', raw_text, re.DOTALL)
                if json_match:
                    contract_json = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        # Ensure we have default contract if none parsed
        if not contract_json:
            contract_json = {"side_effects": ["none"], "max_runtime_ms": 5000}

        return code, contract_json

    def _build_contract(
        self, tool_name: str, contract_json: dict
    ) -> BehaviorContract | None:
        """Build a BehaviorContract from parsed JSON."""
        try:
            return BehaviorContract.from_generated(tool_name, contract_json)
        except ContractValidationError as exc:
            logger.warning("Contract validation failed for '%s': %s", tool_name, exc)
            return None

    # ── Stage 4: Contract Check ──────────────────────────────────────────

    def _check_contract(self, code: str, contract: BehaviorContract) -> bool:
        """Check that code complies with the declared contract."""
        return contract.verify_code_compliance(code).compliant

    # ── Stage 5: Sandbox Forge ───────────────────────────────────────────

    def _forge_tool(self, spec: ImprovementSpec, code: str) -> dict:
        """Forge the tool through the ToolPlugin's forge_cycle."""
        try:
            # Capture pre-forge snapshot
            self._capture_snapshot(spec.function_name)

            # Run the closed forge cycle
            result = self._tools.forge_cycle(
                spec=spec,
                code=code,
                llm_backend=self._llm,
            )
            if result.success:
                return {"success": True, "tool_name": result.tool_name}
            else:
                error_msg = ""
                for stage in result.stages:
                    if not stage.success and stage.error:
                        error_msg = stage.error
                        break
                return {"success": False, "error": error_msg or "Forge cycle failed."}
        except Exception as exc:
            logger.error("Forge failed: %s", exc)
            return {"success": False, "error": str(exc)}

    # ── Stage 7: Online Verify ───────────────────────────────────────────

    def _verify_online(self, tool_name: str) -> _VerifyResult:
        """Call the tool 3 times and count consecutive failures."""
        failures = 0
        for _ in range(3):
            try:
                result = self._tools.call(tool_name)
                if isinstance(result, dict) and result.get("success"):
                    failures = 0  # reset on success
                else:
                    failures += 1
            except Exception:
                failures += 1
                logger.debug(
                    "Online verification call failed for '%s'.", tool_name, exc_info=True
                )
            if failures >= self.rollback_on_failure_count:
                break
        return _VerifyResult(consecutive_failures=failures)

    # ── Stage 8: Quality Evaluation ──────────────────────────────────────

    def _capture_snapshot(self, tool_name: str = "") -> ToolSnapshot:
        """Capture current tool + knowledge state as a snapshot."""
        try:
            tool_list = dict(self._tools.list_tools())
        except Exception:
            tool_list = {}

        try:
            forged_list = dict(self._tools.list_forged())
        except Exception:
            forged_list = {}

        try:
            kn_count = getattr(self._knowledge, "node_count", 0)
        except Exception:
            kn_count = 0

        snapshot = ToolSnapshot(
            tool_name=tool_name,
            code=None,
            tool_list_snapshot=tool_list,
            forged_list_snapshot=forged_list,
            knowledge_node_count=kn_count,
            captured_at=now().isoformat(),
        )

        if tool_name:
            self._snapshots[tool_name] = snapshot

        return snapshot

    def _evaluate_quality_delta(self, before: ToolSnapshot) -> QualityDelta:
        """Compare current state against a before snapshot.

        Checks:
        - Tool count didn't decrease
        - Knowledge didn't shrink >20%
        """
        try:
            current_tools = dict(self._tools.list_tools())
        except Exception:
            current_tools = {}

        before_count = len(before.tool_list_snapshot)
        after_count = len(current_tools)

        if after_count < before_count:
            return QualityDelta(
                degraded=True,
                reason=(
                    f"Tool count decreased: {before_count} → {after_count}"
                ),
            )

        # Criterion 2: Knowledge stability
        before_kn = getattr(before, 'knowledge_node_count', None)
        if before_kn is not None and before_kn > 0:
            current_kn = getattr(self._knowledge, 'node_count', 0)
            if current_kn < before_kn * 0.8:
                return QualityDelta(
                    degraded=True,
                    reason=f"Knowledge nodes decreased significantly: {before_kn} → {current_kn}",
                )

        return QualityDelta(degraded=False)

    # ── Rollback ─────────────────────────────────────────────────────────

    def _rollback(
        self, tool_name: str, snapshot: ToolSnapshot | None
    ) -> None:
        """Roll back a failed deployment.

        Removes the newly forged tool. If a snapshot of an older version
        exists, it can be restored.
        """
        try:
            self._tools.rollback(tool_name)
            logger.info("Rolled back tool '%s'.", tool_name)
        except Exception as exc:
            logger.error("Rollback of '%s' failed: %s", tool_name, exc)

        # Clean up snapshot
        self._snapshots.pop(tool_name, None)

    def _save_snapshot(self, tool_name: str, code: str) -> None:
        """Save a successful deployment snapshot."""
        snapshot = self._capture_snapshot(tool_name)
        if code:
            snapshot.code = code
        self._snapshots["last_success"] = snapshot

    # ── Background Loop ──────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Background thread target — periodic assessment and evolution."""
        logger.info("AutonomousEvolutionLoop background thread running.")

        while True:
            with self._lock:
                if not self._running:
                    break
                paused = self._paused
                quota_exhausted = (
                    self._improvements_this_session >= self.max_improvements_per_session
                )
                last_cycle = self._last_cycle_at

            if paused:
                time_module.sleep(5.0)
                continue

            if quota_exhausted:
                time_module.sleep(10.0)
                continue

            # Rate limit wait using cached _last_cycle_at
            if last_cycle:
                try:
                    last_time = datetime.fromisoformat(last_cycle)
                    elapsed = (now() - last_time).total_seconds()
                    wait = self.min_interval_seconds - elapsed
                    if wait > 0:
                        time_module.sleep(min(wait, 10.0))
                        continue
                except (ValueError, TypeError):
                    pass

            try:
                # run_one_cycle() handles _assess_need() + skip internally
                result = self.run_one_cycle()

                cycle_record = {
                    "success": result.success,
                    "skipped": result.skipped,
                    "stage": result.stage,
                    "error": result.error,
                    "timestamp": now().isoformat(),
                }
                if result.spec:
                    cycle_record["tool_name"] = result.spec.function_name

                with self._lock:
                    self._cycle_history.append(cycle_record)
                    # Keep only last 50 cycle records
                    if len(self._cycle_history) > 50:
                        self._cycle_history = self._cycle_history[-50:]

                # Save state after each cycle
                self._save_state()

                if result.skipped:
                    time_module.sleep(60)
                elif not result.success:
                    time_module.sleep(30)
                else:
                    time_module.sleep(5)

            except Exception:
                logger.error(
                    "Error in _run_loop — will retry after delay.",
                    exc_info=True,
                )
                time_module.sleep(10.0)

    # ── State Persistence ────────────────────────────────────────────────

    def _save_state(self) -> None:
        """Persist runtime state to agent_workspace/state/evolution_loop.json."""
        try:
            self._STATE_DIR.mkdir(parents=True, exist_ok=True)
            state_path = self._STATE_DIR / self._STATE_FILE
            state = {
                "improvements_this_session": self._improvements_this_session,
                "last_cycle_at": self._last_cycle_at,
                "cycle_history": self._cycle_history[-50:],
                "spec_counter": self._spec_counter,
                "last_trigger_scores": self._last_trigger_scores,
                "last_triggered_by": self._last_triggered_by,
                "saved_at": now().isoformat(),
            }
            state_path.write_text(
                json.dumps(state, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            logger.debug("Failed to save evolution loop state.", exc_info=True)

    def _load_state(self) -> None:
        """Load persisted state from disk. Expire state older than 24 hours."""
        try:
            state_path = self._STATE_DIR / self._STATE_FILE
            if not state_path.exists():
                return

            raw = state_path.read_text(encoding="utf-8")
            state = json.loads(raw)

            # Check age
            saved_at = state.get("saved_at", "")
            if saved_at:
                try:
                    saved_time = datetime.fromisoformat(saved_at)
                    age = (now() - saved_time).total_seconds()
                    if age > 86400:  # 24 hours
                        logger.info(
                            "Evolution loop state expired (age: %.0fh). Starting fresh.",
                            age / 3600,
                        )
                        return
                except (ValueError, TypeError):
                    pass

            # Restore counters
            self._improvements_this_session = state.get(
                "improvements_this_session", 0
            )
            self._last_cycle_at = state.get("last_cycle_at")
            self._cycle_history = state.get("cycle_history", [])
            self._spec_counter = state.get("spec_counter", {})
            self._last_trigger_scores = state.get("last_trigger_scores", {})
            self._last_triggered_by = state.get("last_triggered_by", [])

            logger.info(
                "Loaded evolution loop state: %d improvements, %d cycle records.",
                self._improvements_this_session,
                len(self._cycle_history),
            )
        except Exception:
            logger.debug("Failed to load evolution loop state.", exc_info=True)


# ── Package-level evolution adapter ──────────────────────────────────────────

class EvolutionError(Exception):
    """Raised when an evolution stage fails in a way that should prevent
    the mutation from being applied."""


def _minimal_sandbox_env() -> dict[str, str]:
    """Return a minimal safe environment for sandbox subprocess execution."""
    import os as _os
    if _os.name == "nt":
        env = {
            "PYTHONPATH": "",
            "PATH": _os.environ.get("PATH", ""),
            "SystemRoot": _os.environ.get("SystemRoot", "C:\\Windows"),
        }
        system_drive = _os.environ.get("SYSTEMDRIVE", "C:")
        if system_drive:
            env["SYSTEMDRIVE"] = system_drive
        return env
    else:
        return {"PYTHONPATH": "", "PATH": "/usr/bin:/bin"}


def _build_sandbox_test_script(
    *,
    code: str,
    tool_name: str,
    allowed_modules: frozenset,
    blacklisted_calls: frozenset,
    blacklisted_modules: frozenset,
) -> str:
    """Build a self-contained test script with embedded AST validation.

    The returned script string performs AST-level sandbox checks (import
    whitelist, call blacklist) before exec-ing the code and calling the
    tool's main() function.  All validation logic is embedded so the
    subprocess needs no imports from the main codebase.
    """
    lines = [
        "# Auto-generated sandbox smoke test — do not edit",
        "import ast, json, sys",
        "",
        f"_ALLOWED = {allowed_modules!r}",
        f"_CALL_BLACKLIST = {blacklisted_calls!r}",
        f"_MODULE_BLACKLIST = {blacklisted_modules!r}",
        "",
        f"_CODE = {code!r}",
        f"_TOOL_NAME = {tool_name!r}",
        "",
        "errors = []",
        "",
        "# Step 0: syntax check",
        "try:",
        "    tree = ast.parse(_CODE)",
        "except SyntaxError as e:",
        "    print(json.dumps({'passed': False, 'stage': 'syntax',"
        "                      'error': f'SyntaxError: {e}'}))",
        "    sys.exit(0)",
        "",
        "# Step 1: import validation",
        "for node in ast.walk(tree):",
        "    if isinstance(node, ast.Import):",
        "        for alias in node.names:",
        "            top = alias.name.split('.')[0]",
        "            if top in _MODULE_BLACKLIST:",
        "                errors.append(f'blocked_import: {top} ({alias.name})')",
        "            elif top not in _ALLOWED:",
        "                errors.append(f'unlisted_import: {top} ({alias.name})')",
        "    elif isinstance(node, ast.ImportFrom):",
        "        if node.module:",
        "            top = node.module.split('.')[0]",
        "            if top in _MODULE_BLACKLIST:",
        "                errors.append(f'blocked_import: {top} ({node.module})')",
        "            elif top not in _ALLOWED:",
        "                errors.append(f'unlisted_import: {top} ({node.module})')",
        "",
        "# Build import alias map for call resolution",
        "alias_map = {}",
        "for node in ast.walk(tree):",
        "    if isinstance(node, ast.Import):",
        "        for alias in node.names:",
        "            alias_map[alias.asname or alias.name.split('.')[0]] = alias.name",
        "    elif isinstance(node, ast.ImportFrom):",
        "        if node.module:",
        "            for alias in node.names:",
        "                full = f'{node.module}.{alias.name}'",
        "                alias_map[alias.asname or alias.name] = full",
        "",
        "# Step 2: call target validation",
        "for node in ast.walk(tree):",
        "    if isinstance(node, ast.Call):",
        "        func = node.func",
        "        # Direct name call: eval(...)",
        "        if isinstance(func, ast.Name):",
        "            if func.id in _CALL_BLACKLIST:",
        "                errors.append(f'blocked_call: {func.id}()')",
        "        # Attribute call: os.system(...), import os as foo; foo.system(...)",
        "        elif isinstance(func, ast.Attribute):",
        "            # Walk the attribute chain to get the base name",
        "            base = func",
        "            while isinstance(base, ast.Attribute):",
        "                base = base.value",
        "            if isinstance(base, ast.Name):",
        "                resolved = alias_map.get(base.id, base.id)",
        "                top = resolved.split('.')[0]",
        "                if top in _MODULE_BLACKLIST:",
        "                    errors.append(f'blocked_call: {resolved} access')",
        "            # Check the method name against blacklist too",
        "            if func.attr in _CALL_BLACKLIST:",
        "                errors.append(f'blocked_call: .{func.attr}()')",
        "",
        "# Report AST validation failures early",
        "if errors:",
        "    print(json.dumps({'passed': False, 'stage': 'ast_validation',",
        "                      'error': '; '.join(errors)}))",
        "    sys.exit(0)",
        "",
        "# Step 3: exec and smoke test",
        "try:",
        "    exec(_CODE)",
        "    result = main()",
        "    print(json.dumps({'passed': True, 'result': str(result)}))",
        "except Exception as e:",
        "    print(json.dumps({'passed': False, 'stage': 'runtime',",
        "                      'error': f'{type(e).__name__}: {e}'}))",
    ]
    return "\n".join(lines) + "\n"


def create_package_evolver(runtime):
    """Create (gap_detector, mutation_generator, contract_checker, online_verifier)
    callables for use with AgentPackage.evolve().

    Args:
        runtime: AgentRuntime instance providing access to plugins, config,
                 and the LLM backend (stored at runtime._llm_backend).

    Returns:
        Tuple of four callables compatible with AgentPackage.evolve().
    """
    import json as _json  # noqa: F841 — used in Task 3 (mutation_generator)
    from tain_agent.evolution.behavior_contract import BehaviorContract
    from tain_agent.package.evolution import Mutation
    from tain_agent.package import LayerKind

    # Extract dependencies from runtime
    llm_backend = getattr(runtime, '_llm_backend', None)  # noqa: F841 — used in Task 3 (mutation_generator)
    tool_plugin = runtime.get_plugin("ToolPlugin")
    knowledge_plugin = runtime.get_plugin("KnowledgePlugin")  # noqa: F841 — used in Task 4 (online_verifier)
    _ = knowledge_plugin  # suppress unused warning until wired in Task 4

    def gap_detector(package):
        """Detect capability gaps by comparing tool count against threshold.

        Returns a dict with capability_id, description, and gap_score
        suitable for mutation_generator, or None if no gap detected.
        """
        try:
            tools = tool_plugin.list_tools() if hasattr(tool_plugin, 'list_tools') else []
            count = len(tools)
        except Exception:
            count = 0

        if count >= 10:
            return None  # No gap — sufficient tools

        gap_score = round((10 - count) / 10, 4)
        return {
            "capability_id": f"capability_gap_{count}_tools",
            "description": (
                f"Agent has only {count} tools (threshold: 10). "
                f"Gap score: {gap_score}. Generate a useful new tool."
            ),
            "gap_score": gap_score,
            "tool_count": count,
        }

    def mutation_generator(gap, package):
        """Generate tool code via LLM from a gap specification.

        Uses the LLM backend to produce Python code implementing the
        capability described by the gap. Returns a Mutation with the
        generated code as a file to write.
        """
        if llm_backend is None:
            raise EvolutionError("No LLM backend available for code generation")

        capability_id = gap.get("capability_id", "unknown")
        description = gap.get("description", "")

        prompt = (
            f"You are generating Python tool code for a self-evolving agent.\n\n"
            f"Capability needed: {capability_id}\n"
            f"Description: {description}\n\n"
            f"Generate a single complete Python function that implements this "
            f"capability. The code will run in a sandbox with limited imports "
            f"(stdlib whitelist plus declared dependencies).\n\n"
            f"Return a JSON object with these keys:\n"
            f'  "code": The complete Python function as a string.\n'
            f'  "tool_name": A snake_case name for the tool.\n'
            f'  "description": What the tool does (one line).\n'
            f'  "parameters": JSON Schema for the function parameters.\n'
            f'  "dependencies": List of pip package specs needed (e.g. ["requests"]).\n'
            f'  "test_code": A short assertion to verify the tool works.\n'
        )

        try:
            response = llm_backend.create_message(
                system_prompt="You are a Python code generator for agent tools.",
                messages=[{"role": "user", "content": prompt}],
                tools=[],
            )
            text = (
                "\n".join(response.text_blocks)
                if hasattr(response, 'text_blocks')
                else str(response)
            )
            # Extract JSON from code fences if present
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            gen_result = _json.loads(text.strip())
        except Exception as exc:
            raise EvolutionError(f"Code generation failed: {exc}") from exc

        code = gen_result.get("code", "")
        tool_name = gen_result.get("tool_name", capability_id)
        if not code:
            raise EvolutionError("LLM returned empty code for mutation")

        # Build a clean importable module from the LLM-generated code.
        # The LLM is responsible for declaring its own imports.
        lines: list[str] = []
        lines.append(code)
        lines.append("")
        lines.append("")
        lines.append(f"# Tool: {tool_name}")
        lines.append(f"# Description: {gen_result.get('description', '')}")
        lines.append(f"# Generated via autonomous evolution")
        module_code = "\n".join(lines)

        file_path = f"capability/tools/forged/{tool_name}.py"
        return Mutation(
            layer=LayerKind.CAPABILITY,
            change_type="new_tool",
            detail=f"Auto-generated tool '{tool_name}': {gen_result.get('description', '')}",
            files_to_write=[(file_path, module_code.encode("utf-8"))],
            manifest_patch={
                "capability": {
                    "tools": [{"name": tool_name, "version": "1.0.0",
                               "path": file_path, "hash": ""}],
                },
            },
            source_gap=capability_id,
        )

    def contract_checker(mutation, package):
        contract = BehaviorContract()
        try:
            for rel_path, content_bytes in mutation.files_to_write:
                code = content_bytes.decode("utf-8")
                result = contract.verify_code_compliance(code)
                if not result.passed:
                    return False, [f"{rel_path}: {result.errors}"]
            return True, []
        except Exception as e:
            return False, [str(e)]

    def online_verifier(mutation, package):
        """Smoke-test generated tools via sandbox execution.

        Writes generated files into a temporary directory (never touching
        the package's real files), then runs each through AST validation
        and a subprocess smoke test with a 5-second timeout.
        """
        import subprocess as _sp
        import sys as _sys
        import tempfile as _tempfile

        # Sandbox rules — embedded in the test script for AST validation
        _SANDBOX_ALLOWED_MODULES = frozenset({
            "json", "datetime", "pathlib", "typing", "hashlib", "math",
            "collections", "itertools", "functools", "textwrap", "re", "string",
            "dataclasses", "enum", "uuid", "statistics", "csv", "base64",
            "copy", "random", "html", "xml", "argparse", "logging",
        })
        _SANDBOX_BLACKLIST_CALLS = frozenset({
            "eval", "exec", "compile", "__import__", "open",
        })
        _SANDBOX_BLACKLIST_MODULES = frozenset({
            "os", "sys", "subprocess", "shutil", "socket", "ctypes",
            "multiprocessing", "signal", "builtins", "importlib",
            "urllib", "http", "ftplib", "smtplib", "telnetlib",
            "requests", "pdb", "code", "traceback", "inspect",
            "pip", "setuptools", "pkg_resources",
        })

        errors: list[str] = []
        for rel_path, content_bytes in mutation.files_to_write:
            code = content_bytes.decode("utf-8")
            tool_name = Path(rel_path).stem  # filename without .py

            # Write code to a temp directory — never touch package files
            tmp_dir = _tempfile.mkdtemp(prefix="tain_smoke_")
            tool_path = Path(tmp_dir) / f"{tool_name}.py"
            tool_path.write_text(code)

            try:
                # Build a self-contained test script that validates AST
                # before exec-ing and runs the result through a smoke test
                test_script = _build_sandbox_test_script(
                    code=code,
                    tool_name=tool_name,
                    allowed_modules=_SANDBOX_ALLOWED_MODULES,
                    blacklisted_calls=_SANDBOX_BLACKLIST_CALLS,
                    blacklisted_modules=_SANDBOX_BLACKLIST_MODULES,
                )

                proc = _sp.run(
                    [_sys.executable, "-c", test_script],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=_minimal_sandbox_env(),
                )

                # Check returncode first — subprocess crash means stderr has
                # the real error, not stdout
                if proc.returncode != 0:
                    stderr_tail = proc.stderr.strip().split("\n")[-1] if proc.stderr else "no stderr"
                    errors.append(
                        f"{rel_path}: subprocess crashed (exit {proc.returncode}) — {stderr_tail}"
                    )
                    continue

                stdout = proc.stdout.strip()
                if not stdout:
                    errors.append(f"{rel_path}: smoke test produced no output")
                    continue

                try:
                    output = _json.loads(stdout)
                except Exception:
                    errors.append(
                        f"{rel_path}: smoke test returned non-JSON output: {stdout[:200]}"
                    )
                    continue

                if not output.get("passed", False):
                    errors.append(
                        f"{rel_path}: smoke test failed — {output.get('error', output.get('reason', 'unknown'))}"
                    )
            except _sp.TimeoutExpired:
                errors.append(f"{rel_path}: smoke test timed out after 5s")
            except Exception as exc:
                errors.append(f"{rel_path}: smoke test error — {exc}")
            finally:
                # Clean up temp directory
                import shutil as _shutil
                _shutil.rmtree(tmp_dir, ignore_errors=True)

        return (len(errors) == 0, errors)

    return gap_detector, mutation_generator, contract_checker, online_verifier
