"""
Self-Improvement Loop — 改进循环调度器

The scheduler that periodically assesses the agent, identifies improvement
opportunities, and executes the pipeline. This transforms passive improvement
(agent manually calls forge_tool) into active, systematic self-evolution.

Key safety properties:
  - Rate-limited: minimum interval between improvement cycles
  - Decision-logged: every action recorded for traceability
  - Reversible: forged tools can be removed if problematic
  - Observable: status reports at every stage
  - Quota-enforced: max improvements per session

This is the "三生万物" — from the pipeline (三) comes the continuous
generation of new capabilities (万物).
"""

import os
import threading
import time as time_module
from datetime import datetime
from pathlib import Path
import json

from tain_agent.core.time_utils import now
from typing import Optional, Callable


class ImprovementLoop:
    """Cyclic scheduler for continuous self-improvement."""

    def __init__(self, pipeline=None, capability_registry=None, decision_log=None,
                 memory=None, tool_registry=None):
        self._pipeline = pipeline
        self._capability_registry = capability_registry
        self._decision_log = decision_log
        self._memory = memory
        self._tool_registry = tool_registry

        self.min_interval_seconds = 300
        self.max_improvements_per_session = 10
        self.require_confirmation = False
        self.auto_approve_safe = True

        self.trigger_config = {
            "min_trigger_score": 0.01,
            "capability_gap": {"enabled": True,  "threshold": 0.0, "weight": 0.10},
            "code_health":    {"enabled": True,  "threshold": 0.50, "weight": 0.25},
            "knowledge_fresh": {"enabled": True, "threshold": 0.30, "weight": 0.25},
            "tool_fitness":   {"enabled": True,  "threshold": 0.10, "weight": 0.15},
            "tool_dedup":     {"enabled": True,  "threshold": 0.40, "weight": 0.10},
            "subgraph_balance": {"enabled": True, "threshold": 0.30, "weight": 0.15},
        }
        self._last_trigger_scores: dict = {}
        self._last_triggered_by: Optional[str] = None

        self._running = False
        self._last_cycle_at: Optional[str] = None
        self._improvements_this_session = 0
        self._session_started_at: Optional[str] = None
        self._cycle_history: list[dict] = []
        self._paused = False
        self._thread: Optional[threading.Thread] = None

        self._no_improvement_streak = 0
        self._max_no_improvement = 3
        self._daemon_mode = os.environ.get("TAO_DAEMON", "") == "1"
        self._auto_resume_cooldown = 60  # seconds before auto-resume in daemon mode
        self._paused_at: Optional[float] = None

        self._on_cycle_start: Optional[Callable] = None
        self._on_cycle_complete: Optional[Callable] = None
        self._on_gap_detected: Optional[Callable] = None
        self._code_generator: Optional[Callable] = None

        self._load_state()

    # ── Configuration ──────────────────────────────────────────────────

    def configure(self, min_interval_seconds: int = None,
                  max_improvements: int = None,
                  require_confirmation: bool = None,
                  auto_approve_safe: bool = None) -> dict:
        if min_interval_seconds is not None:
            self.min_interval_seconds = min_interval_seconds
        if max_improvements is not None:
            self.max_improvements_per_session = max_improvements
        if require_confirmation is not None:
            self.require_confirmation = require_confirmation
        if auto_approve_safe is not None:
            self.auto_approve_safe = auto_approve_safe
        return self.get_config()

    def get_config(self) -> dict:
        return {
            "min_interval_seconds": self.min_interval_seconds,
            "max_improvements_per_session": self.max_improvements_per_session,
            "require_confirmation": self.require_confirmation,
            "auto_approve_safe": self.auto_approve_safe,
            "improvements_this_session": self._improvements_this_session,
            "running": self._running,
            "paused": self._paused,
        }

    def configure_triggers(self, min_trigger_score: float = None,
                          dim_settings: dict = None) -> dict:
        if min_trigger_score is not None:
            self.trigger_config["min_trigger_score"] = min_trigger_score
        if dim_settings:
            for dim, settings in dim_settings.items():
                if dim in self.trigger_config:
                    self.trigger_config[dim].update(settings)
        return self.trigger_config

    def set_code_generator(self, generator: Callable) -> None:
        self._code_generator = generator

    def on_cycle_start(self, callback: Callable) -> None:
        self._on_cycle_start = callback

    def on_cycle_complete(self, callback: Callable) -> None:
        self._on_cycle_complete = callback

    def on_gap_detected(self, callback: Callable) -> None:
        self._on_gap_detected = callback

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> dict:
        """Enable improvement capability (cognitive-driven)."""
        if self._running:
            return {"success": False, "error": "Loop is already active."}

        if not self._pipeline:
            return {"success": False, "error": "No pipeline configured."}
        if not self._capability_registry:
            return {"success": False, "error": "No capability registry configured."}

        if self.require_confirmation:
            self.configure(require_confirmation=False)
        if not self.auto_approve_safe:
            self.configure(auto_approve_safe=True)

        self._running = True
        self._paused = False
        self._session_started_at = now().isoformat()
        self._improvements_this_session = 0

        if self._decision_log:
            self._decision_log.record(
                context={"action": "improvement_loop_start", "mode": "cognitive_driven"},
                decision_type="loop_control",
                options_considered=[{"option": "start", "config": self.get_config()}],
                chosen_option="start",
                reasoning="Enabling cognitive-driven improvement.",
                expected_outcome="Agent will improve when cognitive loop detects need.",
                phase="evolve",
            )

        self._save_state()
        print("  🔄 自我改进循环已启用（认知驱动）")

        return {
            "success": True,
            "message": "Improvement loop enabled (cognitive-driven).",
            "config": self.get_config(),
        }

    def stop(self) -> dict:
        if not self._running:
            return {"success": False, "error": "Loop is not running."}
        self._running = False
        self._save_state()
        print("  ⏹️ 自我改进循环已停止。")
        return {"success": True, "message": "Improvement loop stopped."}

    def pause(self) -> dict:
        if not self._running:
            return {"success": False, "error": "Loop is not running."}
        self._paused = True
        return {"success": True, "message": "Loop paused."}

    def resume(self) -> dict:
        if not self._running:
            return {"success": False, "error": "Loop is not running."}
        self._paused = False
        self._no_improvement_streak = 0
        return {"success": True, "message": "Loop resumed."}

    # ── Core Execution ─────────────────────────────────────────────────

    def run_one_cycle(self, code: str = "", parameters: dict = None) -> dict:
        """Execute a single improvement cycle."""
        cycle_start = now()

        checks = self._preflight_checks()
        if not checks["can_proceed"]:
            return {"success": False, "error": checks["reason"], "cycle_completed": False}

        self._safe_callback(self._on_cycle_start)
        self._last_cycle_at = cycle_start.isoformat()
        pipeline_result = self._pipeline.run_full_pipeline(code=code, parameters=parameters)

        pipeline_result = self._maybe_generate_fallback_code(pipeline_result, code, parameters)
        real_improvement = self._detect_real_improvement(pipeline_result)
        self._save_cycle_record(cycle_start, pipeline_result, real_improvement)
        self._safe_callback(self._on_cycle_complete, pipeline_result)
        self._log_cycle_decision(pipeline_result)
        self._reinforce_personality()

        return {
            "success": True,
            "cycle_completed": pipeline_result.overall_passed,
            "summary": pipeline_result.summary,
            "spec": pipeline_result.spec.to_dict() if pipeline_result.spec else None,
            "stages": [s.to_dict() for s in pipeline_result.stages],
        }

    def _detect_real_improvement(self, pipeline_result) -> bool:
        """Detect if result is real improvement or just 'no_gaps'."""
        if not pipeline_result.overall_passed:
            return False
        for stage in pipeline_result.stages:
            if stage.stage_name == "analyze":
                output_str = str(stage.output)
                if "'action': 'no_gaps'" in output_str or '"action": "no_gaps"' in output_str:
                    return False
        return True

    def _maybe_generate_fallback_code(self, pipeline_result, code: str, parameters: dict):
        """Try built-in or external code generation if pipeline didn't pass."""
        if pipeline_result.overall_passed or code:
            return pipeline_result

        spec = pipeline_result.spec
        if not spec:
            return pipeline_result

        gen_code, gen_params = self._builtin_code_gen(spec)
        if gen_code:
            return self._pipeline.run_full_pipeline(code=gen_code, parameters=gen_params or {})

        if self._code_generator:
            forge_stage = self._find_forge_stage_needing_code(pipeline_result)
            if forge_stage:
                return self._try_external_code_generator(spec)

        return pipeline_result

    def _find_forge_stage_needing_code(self, pipeline_result) -> Optional[object]:
        for stage in pipeline_result.stages:
            if stage.stage_name == "forge" and stage.metadata.get("needs_code"):
                return stage
        return None

    def _try_external_code_generator(self, spec) -> object:
        try:
            generated = self._code_generator(spec)
            if generated:
                gen_code, gen_params = generated
                return self._pipeline.run_full_pipeline(code=gen_code, parameters=gen_params)
        except Exception:
            pass
        return None

    def _save_cycle_record(self, cycle_start, pipeline_result, real_improvement: bool) -> None:
        cycle_record = {
            "timestamp": cycle_start.isoformat(),
            "pipeline_result": pipeline_result.to_dict(),
            "improvement_made": real_improvement,
        }
        if real_improvement:
            self._improvements_this_session += 1
            cycle_record["improvement_number"] = self._improvements_this_session
        else:
            cycle_record["improvement_number"] = None

        self._cycle_history.append(cycle_record)
        self._save_state()

    def _safe_callback(self, callback: Optional[Callable], *args) -> None:
        if callback:
            try:
                callback(*args)
            except Exception:
                pass

    def _log_cycle_decision(self, pipeline_result) -> None:
        if not self._decision_log:
            return
        self._decision_log.record(
            context={"action": "improvement_cycle", "cycle_number": len(self._cycle_history)},
            decision_type="improvement_cycle",
            options_considered=[{"option": "run_cycle", "with_code": False}],
            chosen_option="run_cycle",
            reasoning=f"Cycle #{len(self._cycle_history)}: "
                      f"{'PASSED' if pipeline_result.overall_passed else 'FAILED'}. "
                      f"{pipeline_result.summary}",
            expected_outcome=pipeline_result.summary,
            phase="evolve",
        )

    # ── Smart Improve ─────────────────────────────────────────────────

    def _run_smart_improve_cycle(self, triggered_by: list) -> dict:
        """Execute improvement cycle for non-capability-gap dimensions."""
        cycle_start = now()
        try:
            from tain_agent.tools.forged.smart_improve import smart_improve
            result = smart_improve(action="improve", auto_fix=True)
            return self._record_smart_improve_result(cycle_start, result, triggered_by)
        except Exception as e:
            return {"success": False, "cycle_completed": False, "summary": f"smart_improve failed: {e}"}

    def _record_smart_improve_result(self, cycle_start, result: dict, triggered_by: list) -> dict:
        improvement_made = result.get("fixed_count", 0) > 0

        cycle_record = {
            "timestamp": cycle_start.isoformat(),
            "pipeline_result": {"summary": result.get("summary", "smart_improve executed")},
            "improvement_made": improvement_made,
            "improvement_number": None,
            "smart_improve_result": result,
        }

        if improvement_made:
            self._improvements_this_session += 1
            cycle_record["improvement_number"] = self._improvements_this_session

        self._cycle_history.append(cycle_record)
        self._last_cycle_at = cycle_start.isoformat()
        self._save_state()
        self._reinforce_personality()

        if self._decision_log:
            self._decision_log.record(
                context={"action": "smart_improve_cycle"},
                decision_type="improvement_cycle",
                options_considered=[{"option": "smart_improve",
                                     "dimensions": [t.get('dimension') for t in triggered_by]}],
                chosen_option="smart_improve",
                reasoning=f"Non-gap improvement via smart_improve. {result.get('summary', '')}",
                expected_outcome=result.get("summary", ""),
                phase="evolve",
            )

        return {
            "success": True,
            "cycle_completed": improvement_made,
            "summary": result.get("summary", "smart_improve cycle completed"),
            "improvement_made": improvement_made,
        }

    # ── Execute Once If Needed ────────────────────────────────────────

    def execute_once_if_needed(self) -> dict:
        """Assess need and execute one cycle ONLY if should_trigger."""
        assessment = self.assess()

        if not assessment.get("should_trigger", False):
            return {
                "triggered": False,
                "assessment": assessment,
                "reason": f"need_score {assessment.get('need_score', 0)} < threshold",
            }

        if not self.can_trigger():
            return {
                "triggered": False,
                "assessment": assessment,
                "reason": "Cannot trigger: paused, quota exhausted, or interval not elapsed.",
            }

        result = self._route_cycle_by_triggered_dims(assessment)
        self._update_non_improvement_streak(result)

        return {"triggered": True, "assessment": assessment, "result": result}

    def _route_cycle_by_triggered_dims(self, assessment: dict) -> dict:
        triggered_by = assessment.get('triggered_by', [])
        triggered_dims = [t.get('dimension') for t in triggered_by]
        coverage = assessment.get('scores', {}).get('capability_gap', 1.0)

        if 'capability_gap' in triggered_dims and coverage > 0:
            return self.run_one_cycle()
        elif triggered_dims:
            return self._run_smart_improve_cycle(triggered_by)
        return self.run_one_cycle()

    def _update_non_improvement_streak(self, result: dict) -> None:
        improved = result.get('improvement_made', result.get('cycle_completed', False))
        if not improved:
            self._no_improvement_streak = getattr(self, '_no_improvement_streak', 0) + 1
            max_streak = getattr(self, '_max_no_improvement', 3)
            if self._no_improvement_streak >= max_streak:
                if self._daemon_mode:
                    print(f"  ⏸️ {self._no_improvement_streak} consecutive non-improvement — "
                          f"auto-resume in {self._auto_resume_cooldown}s (daemon mode).")
                    self._paused = True
                    self._paused_at = time_module.time()
                else:
                    print(f"  ⏸️ {self._no_improvement_streak} consecutive non-improvement — auto-pausing.")
                    self._paused = True
        else:
            self._no_improvement_streak = 0

    # ── Background Loop ────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Background thread: periodically assess and improve."""
        print("  🔄 自我改进循环已启动（后台线程）")

        while self._running:
            try:
                if not self._handle_rate_limit_wait():
                    continue
                if self._paused:
                    if self._daemon_mode and self._paused_at:
                        elapsed = time_module.time() - self._paused_at
                        if elapsed >= self._auto_resume_cooldown:
                            print(f"  ▶️  Auto-resuming after {elapsed:.0f}s cooldown (daemon mode).")
                            self._paused = False
                            self._paused_at = None
                            self._no_improvement_streak = 0
                            continue
                    time_module.sleep(5)
                    continue

                check = self._preflight_checks()
                if not check["can_proceed"]:
                    self._backoff_from_failed_check(check)
                    continue

                self._safe_callback(self._on_cycle_start)
                assessment = self._assess_improvement_need()

                if not assessment.get("should_trigger", False):
                    self._handle_no_need_backoff(assessment)
                    continue

                result = self._execute_triggered_cycle(assessment)
                self._handle_cycle_result(result)

            except Exception as e:
                print(f"  💥 循环错误: {e}")
                time_module.sleep(30)

        print("  ⏹️ 自我改进循环已停止。")

    def _handle_rate_limit_wait(self) -> bool:
        """Handle rate limiting wait. Returns True to proceed."""
        if not self._last_cycle_at:
            return True
        last = datetime.fromisoformat(self._last_cycle_at)
        elapsed = (now() - last).total_seconds()
        if elapsed < self.min_interval_seconds:
            time_module.sleep(min(self.min_interval_seconds - elapsed, 30))
            return False
        return True

    def _backoff_from_failed_check(self, check: dict) -> None:
        retry_time = check.get("retry_after_seconds", 30)
        time_module.sleep(min(retry_time, 30))

    def _handle_no_need_backoff(self, assessment: dict) -> None:
        self._no_need_streak = getattr(self, '_no_need_streak', 0) + 1
        backoff = min(30 * (2 ** min(self._no_need_streak - 1, 6)), 3600)

        if self._decision_log:
            self._decision_log.record(
                context={"action": "improvement_cycle_skipped"},
                decision_type="improvement_cycle",
                options_considered=[{"option": "skip", "reason": "need_score below threshold"}],
                chosen_option="skip",
                reasoning=f"Need score {assessment.get('need_score', 0):.3f} < threshold. Backoff: {backoff}s",
                expected_outcome="Agent does not need improvement.",
                phase="evolve",
            )

        time_module.sleep(backoff)
        if self._state_changed():
            self._no_need_streak = 0

    def _execute_triggered_cycle(self, assessment: dict) -> dict:
        triggered_by = assessment.get('triggered_by', [])
        trigger_reason = triggered_by[0].get('dimension', 'unknown') if triggered_by else 'unknown'
        need_score = assessment.get('need_score', 0)

        print(f"\n{'='*60}")
        print(f"  🔄 自我改进周期 #{len(self._cycle_history) + 1}")
        print(f"  📊 触发维度: {trigger_reason} (需求分数: {need_score:.3f})")
        print(f"{'='*60}")

        coverage = assessment.get('scores', {}).get('capability_gap', 1.0)
        triggered_dims = [t.get('dimension') for t in triggered_by]

        if 'capability_gap' in triggered_dims and coverage > 0:
            return self.run_one_cycle()
        elif triggered_dims:
            return self._run_smart_improve_cycle(triggered_by)
        return self.run_one_cycle()

    def _handle_cycle_result(self, result: dict) -> None:
        self._safe_callback(self._on_cycle_complete, result)
        improved = result.get('cycle_completed', False)
        print(f"  📊 周期完成: {'✅ 成功' if improved else '❌ 失败'}")

        if not improved:
            self._no_improvement_streak += 1
            if self._no_improvement_streak >= self._max_no_improvement:
                print(f"  ⏸️ 自动暂停 - {self._no_improvement_streak} 连续周期无实际改进。")
                self._paused = True
                self._no_improvement_streak = 0
        else:
            self._no_improvement_streak = 0

    # ── Assessment ────────────────────────────────────────────────────

    def assess(self) -> dict:
        return self._assess_improvement_need()

    def can_trigger(self) -> bool:
        if self._paused:
            return False
        if self._improvements_this_session >= self.max_improvements_per_session:
            return False
        if self._last_cycle_at:
            last = datetime.fromisoformat(self._last_cycle_at)
            elapsed = (now() - last).total_seconds()
            if elapsed < self.min_interval_seconds:
                return False
        return True

    def _assess_improvement_need(self) -> dict:
        """Multi-dimensional improvement need assessment."""
        scores = {}
        for dim_name, config in self.trigger_config.items():
            if dim_name == "min_trigger_score" or not config.get("enabled", True):
                continue
            threshold = config.get("threshold", 0)
            score = self._evaluate_dimension(dim_name, threshold)
            scores[dim_name] = score

        total_weight = sum(
            self.trigger_config.get(d, {}).get("weight", 0)
            for d in scores
            if self.trigger_config.get(d, {}).get("enabled", True)
        )

        need_score = sum(
            scores[d] * self.trigger_config.get(d, {}).get("weight", 0) / total_weight
            for d in scores
        ) if total_weight > 0 else 0

        triggered_by = [
            {"dimension": d, "score": scores[d], "threshold": self.trigger_config[d]["threshold"]}
            for d in scores
            if scores[d] > 0
        ]

        should_trigger = need_score >= self.trigger_config["min_trigger_score"]

        self._last_trigger_scores = scores
        self._last_triggered_by = triggered_by

        return {
            "need_score": need_score,
            "min_trigger_score": self.trigger_config["min_trigger_score"],
            "scores": scores,
            "triggered_by": triggered_by,
            "should_trigger": should_trigger,
        }

    def _evaluate_dimension(self, dim_name: str, threshold: float) -> float:
        evaluators = {
            "capability_gap": self._eval_capability_gap,
            "code_health": self._eval_code_health,
            "knowledge_fresh": self._eval_knowledge_fresh,
            "tool_fitness": self._eval_tool_fitness,
            "tool_dedup": self._eval_tool_dedup,
            "subgraph_balance": self._eval_subgraph_balance,
        }
        evaluator = evaluators.get(dim_name)
        if not evaluator:
            return 0.0
        score = evaluator(threshold)
        return max(0.0, min(1.0, score))

    def _reinforce_personality(self) -> dict:
        """Reinforce discovered personality traits after each improvement cycle.

        Gradually increases confidence for traits with < 5 observations,
        giving the agent a stable sense of self over time.
        """
        import json
        personality_path = Path("agent_workspace/state/personality.json")
        if not personality_path.exists():
            return {"reinforced": 0}

        try:
            data = json.loads(personality_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            return {"reinforced": 0}

        traits = data.get("traits", {})
        evolution_log = data.get("evolution_log", [])
        reinforced = 0

        for category, trait_list in traits.items():
            for trait in trait_list:
                confidence = trait.get("confidence", 0.0)
                observations = trait.get("observations", 0)
                if confidence < 0.7 and observations < 5:
                    trait["confidence"] = round(min(confidence + 0.05, 1.0), 2)
                    trait["observations"] = observations + 1
                    trait["last_updated_at"] = now().isoformat()
                    reinforced += 1
                    evolution_log.append({
                        "action": "reinforced_by_cycle",
                        "category": category,
                        "value": trait["value"],
                        "story": f"改进循环自动强化 (cycle #{len(self._cycle_history)})",
                        "at": now().isoformat(),
                    })

        if reinforced > 0:
            data["saved_at"] = now().isoformat()
            personality_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                       encoding="utf-8")

        return {"reinforced": reinforced}

    def _state_fingerprint(self) -> str:
        components = []
        tools_dir = Path("tain_agent/tools/forged")
        if tools_dir.exists():
            components.append(str(sorted([f.name for f in tools_dir.glob("*.py")])))
            components.append(str(tools_dir.stat().st_mtime))
        state_dir = Path("tain_agent/state")
        if state_dir.exists():
            for f in sorted(state_dir.glob("*.json")):
                try:
                    components.append(f"{f.name}:{f.stat().st_size}")
                except Exception:
                    pass
        memory_file = Path("tain_agent/state/memory.json")
        if memory_file.exists():
            components.append(str(memory_file.stat().st_mtime))
        return "|".join(components)

    def _state_changed(self) -> bool:
        current = self._state_fingerprint()
        if hasattr(self, '_last_state_fingerprint'):
            return current != self._last_state_fingerprint
        self._last_state_fingerprint = current
        return True

    # ── Dimension Evaluators ─────────────────────────────────────────

    def _eval_capability_gap(self, threshold: float) -> float:
        if not self._capability_registry:
            return 0.0
        try:
            coverage = self._capability_registry.get_coverage_summary()
            return coverage.get("uncovered_percentage", 0) / 100.0
        except Exception:
            return 0.0

    def _import_tool(self, module_path: str):
        """Import a tool module, falling back to workspace forged_tools if needed."""
        try:
            return __import__(module_path, fromlist=["*"])
        except ImportError:
            # Fallback: add workspace forged_tools to path and retry
            import sys
            from pathlib import Path as _Path
            ws_tools = _Path("agent_workspace/forged_tools").resolve()
            if ws_tools.exists() and str(ws_tools) not in sys.path:
                sys.path.insert(0, str(ws_tools))
                try:
                    mod_name = module_path.rsplit(".", 1)[-1]
                    return __import__(mod_name)
                except ImportError:
                    pass
            raise

    def _eval_code_health(self, threshold: float) -> float:
        try:
            ce = self._import_tool("tain_agent.tools.forged.code_entropy")
            result = ce.analyze_entropy()
            health_score = result.get("health_score", 1.0)
            return max(0.0, threshold - health_score) if health_score < threshold else 0.0
        except Exception:
            return 0.0

    def _eval_knowledge_fresh(self, threshold: float) -> float:
        try:
            kf = self._import_tool("tain_agent.tools.forged.knowledge_freshness")
            result = kf.check_freshness()
            fresh_ratio = result.get("fresh_ratio", 1.0)
            # Empty knowledge graph should trigger knowledge building
            if fresh_ratio == 0.0:
                return 1.0
            return max(0.0, threshold - fresh_ratio) if fresh_ratio < threshold else 0.0
        except Exception:
            return 0.0

    def _eval_tool_fitness(self, threshold: float) -> float:
        try:
            tf = self._import_tool("tain_agent.tools.forged.tool_fitness")
            result = tf.analyze_fitness()
            dead_ratio = result.get("dead_tool_ratio", 0.0)
            return dead_ratio if dead_ratio > threshold else 0.0
        except Exception:
            return 0.0

    def _eval_tool_dedup(self, threshold: float) -> float:
        """Detect duplicate tool implementations by content hash."""
        try:
            import hashlib
            from pathlib import Path as _Path
            tools_dir = _Path("agent_workspace/forged_tools")
            if not tools_dir.exists():
                tools_dir = _Path("tain_agent/tools/forged")
            if not tools_dir.exists():
                return 0.0

            hashes = {}
            total = 0
            duplicates = 0
            for py_file in sorted(tools_dir.glob("*.py")):
                if py_file.name.startswith("_") or "test" in py_file.name.lower():
                    continue
                total += 1
                try:
                    content = py_file.read_text(encoding="utf-8")
                    h = hashlib.md5(content.encode()).hexdigest()
                    if h in hashes:
                        duplicates += 1
                    else:
                        hashes[h] = py_file.name
                except Exception:
                    pass

            if total == 0:
                return 0.0
            dup_ratio = duplicates / total
            return dup_ratio if dup_ratio > threshold else 0.0
        except Exception:
            return 0.0

    def _eval_subgraph_balance(self, threshold: float) -> float:
        try:
            ks = self._import_tool("tain_agent.tools.forged.knowledge_subgraph")
            result = ks.check_balance()
            balance_score = result.get("balance_score", 1.0)
            return max(0.0, threshold - balance_score) if balance_score < threshold else 0.0
        except Exception:
            return 0.0

    # ── Preflight Checks ──────────────────────────────────────────────

    def _preflight_checks(self) -> dict:
        self._running = self._running or True
        self._session_started_at = self._session_started_at or now().isoformat()
        self._paused = self._paused or False

        if self._improvements_this_session >= self.max_improvements_per_session:
            return {
                "can_proceed": False,
                "reason": f"Max improvements reached ({self.max_improvements_per_session}).",
            }

        if self._last_cycle_at:
            last = datetime.fromisoformat(self._last_cycle_at)
            elapsed = (now() - last).total_seconds()
            if elapsed < self.min_interval_seconds:
                return {
                    "can_proceed": False,
                    "reason": f"Rate limited. {self.min_interval_seconds - elapsed:.0f}s remaining.",
                    "retry_after_seconds": self.min_interval_seconds - elapsed,
                }

        need_assessment = self._assess_improvement_need()
        if not need_assessment["should_trigger"]:
            return {
                "can_proceed": False,
                "reason": f"No improvement need. score={need_assessment['need_score']:.3f} < "
                          f"min={need_assessment['min_trigger_score']:.3f}",
                "need_assessment": need_assessment,
                "retry_after_seconds": self.min_interval_seconds,
            }

        return {
            "can_proceed": True,
            "reason": f"Improvement need detected: {need_assessment['triggered_by']}",
            "need_assessment": need_assessment,
        }

    # ── Built-in Code Generator ───────────────────────────────────────

    def _builtin_code_gen(self, spec) -> tuple:
        desc = getattr(spec, 'description', '') or ''
        notes = getattr(spec, 'design_notes', '') or ''
        tool_name = getattr(spec, 'tool_name', '') or getattr(spec, 'capability_id', '') or ''
        combined = f"{desc} {notes}".lower()

        if any(kw in combined for kw in ('knowledge', 'search', 'retrieve', 'index', 'query')):
            return self._gen_knowledge_tool(desc, tool_name)
        if any(kw in combined for kw in ('test', 'validate', 'verify', 'check', 'audit')):
            return self._gen_testing_tool(desc, tool_name)
        if any(kw in combined for kw in ('metric', 'monitor', 'observe', 'collect', 'dashboard')):
            return self._gen_metrics_tool(desc, tool_name)

        return None, None

    def _gen_knowledge_tool(self, desc: str, name: str) -> tuple:
        code = f'''
"""
{desc}
"""
import json

def query(q: str = "", limit: int = 10) -> dict:
    """Query the knowledge system."""
    return {{"query": q, "results": [], "status": "ok"}}

def main(action: str = "query", **kwargs) -> dict:
    return query(kwargs.get("q", ""), kwargs.get("limit", 10))
'''
        params = {"type": "object", "properties": {
            "action": {"type": "string"},
            "q": {"type": "string"},
            "limit": {"type": "integer"}
        }}
        return code, params

    def _gen_testing_tool(self, desc: str, name: str) -> tuple:
        code = f'''
"""
{desc}
"""
import json

def run(target: str = "") -> dict:
    """Run validation checks."""
    results = {{"target": target, "passed": [], "failed": []}}
    return {{"status": "ok", "results": results}}

def main(action: str = "run", **kwargs) -> dict:
    return run(kwargs.get("target", ""))
'''
        params = {"type": "object", "properties": {
            "action": {"type": "string"},
            "target": {"type": "string"}
        }}
        return code, params

    def _gen_metrics_tool(self, desc: str, name: str) -> tuple:
        code = f'''
"""
{desc}
"""
import json
from tain_agent.core.time_utils import now

def collect() -> dict:
    """Collect current metrics."""
    return {{"collected_at": now().isoformat(), "metrics": {{}}}}

def main(action: str = "collect", **kwargs) -> dict:
    return collect()
'''
        params = {"type": "object", "properties": {"action": {"type": "string"}}}
        return code, params

    # ── Status & State ───────────────────────────────────────────────

    def query(self, q: str = "", limit: int = 10) -> dict:
        return {
            "running": self._running,
            "paused": self._paused,
            "improvements_this_session": self._improvements_this_session,
            "last_cycle_at": self._last_cycle_at,
            "cycle_count": len(self._cycle_history),
            "trigger_scores": self._last_trigger_scores,
            "triggered_by": self._last_triggered_by,
        }

    def main(self, action: str = "query", **kwargs) -> dict:
        return self.query(**kwargs)

    def run(self, target: str = "") -> dict:
        return self.query()

    def status_report(self) -> str:
        lines = [
            "=" * 60,
            "  自我改进循环 (Improvement Loop) 状态报告",
            "=" * 60,
            f"  运行状态: {'🔄 运行中' if self._running else '⏹️ 停止中'} "
            f"({'⏸️ 已暂停' if self._paused else '▶️ 活跃'})",
            f"  本会话改进次数: {self._improvements_this_session}/{self.max_improvements_per_session}",
            f"  最后周期时间: {self._last_cycle_at or '无'}",
            f"  周期历史: {len(self._cycle_history)} 个周期",
            "",
            "  触发维度配置:",
            f"    最低触发分数: {self.trigger_config['min_trigger_score']:.3f}",
        ]

        for dim_name, config in self.trigger_config.items():
            if dim_name == "min_trigger_score":
                continue
            enabled = "✓" if config.get("enabled") else "✗"
            threshold = config.get("threshold", 0)
            weight = config.get("weight", 0)
            score = self._last_trigger_scores.get(dim_name, "N/A")
            score_str = f"{score:.3f}" if isinstance(score, float) else str(score)
            lines.append(f"    {enabled} {dim_name}: 阈值={threshold:.2f}, "
                        f"权重={weight:.2f}, 当前分数={score_str}")

        if self._last_trigger_scores:
            lines.append("")
            lines.append("  当前维度分数:")
            for dim, score in self._last_trigger_scores.items():
                should_trigger = "→ 触发" if score > 0 else ""
                lines.append(f"    {dim}: {score:.3f} {should_trigger}")

        improvements = 0
        if self._cycle_history:
            improvements = sum(1 for c in self._cycle_history if c.get("improvement_made"))
            rate = improvements / len(self._cycle_history) * 100
            lines.append("")
            lines.append(f"  改进成功率: {rate:.1f}% ({improvements}/{len(self._cycle_history)})")

        return "\n".join(lines)

    def export_state(self) -> dict:
        return {
            "running": self._running,
            "paused": self._paused,
            "improvements_this_session": self._improvements_this_session,
            "last_cycle_at": self._last_cycle_at,
            "session_started_at": self._session_started_at,
            "cycle_count": len(self._cycle_history),
            "trigger_scores": self._last_trigger_scores,
            "triggered_by": self._last_triggered_by,
            "config": self.get_config(),
        }

    def _save_state(self) -> None:
        try:
            state_dir = Path("tain_agent/state")
            state_dir.mkdir(parents=True, exist_ok=True)
            state_file = state_dir / "improvement_loop.json"

            state = self.export_state()
            state["_saved_at"] = now().isoformat()

            with open(state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"  ⚠️ 状态保存失败: {e}")

    def _load_state(self) -> None:
        try:
            state_file = Path("tain_agent/state/improvement_loop.json")
            if not state_file.exists():
                return

            with open(state_file) as f:
                state = json.load(f)

            self._improvements_this_session = state.get("improvements_this_session", 0)
            self._last_cycle_at = state.get("last_cycle_at")
            self._last_trigger_scores = state.get("trigger_scores", {})

            if state.get("_saved_at"):
                saved_at = datetime.fromisoformat(state["_saved_at"])
                if (now() - saved_at).total_seconds() > 86400:
                    self._improvements_this_session = 0
                    self._last_cycle_at = None
        except Exception:
            pass

    def main(self, action: str = "run", **kwargs) -> dict:
        actions = {
            "query": self.query,
            "run": self.run,
            "collect": self.collect,
            "status": lambda: {"status": self.status_report()},
        }
        return actions.get(action, lambda: {"error": f"Unknown action: {action}"})()

    def collect(self) -> dict:
        return self.query()