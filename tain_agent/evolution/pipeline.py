"""
Self-Improvement Pipeline — 进化流水线

Implements the "分析→设计→锻造→验证→注册" (Analyze → Design → Forge → Verify → Register)
pipeline for systematic, safe, verifiable recursive self-improvement.

Each stage is logged to the Decision Log for full traceability.
This is the operational heart of responsible RSI.

Architecture:
  Stage 1: ANALYZE  — examine current state, identify gaps
  Stage 2: DESIGN   — create a specification for the improvement
  Stage 3: FORGE    — create the tool code (via ToolForge with sandbox)
  Stage 4: VERIFY   — regression tests, integration checks
  Stage 5: REGISTER — register tool, update capability map, log completion
"""

import traceback
from tain_agent.core.time_utils import now
from typing import Optional


class ImprovementSpec:
    """A specification for a capability improvement."""

    def __init__(self, capability_id: str, description: str, tool_name: str = "",
                 tool_description: str = "", design_notes: str = "",
                 success_test: str = "", priority: str = "MEDIUM"):
        self.capability_id = capability_id
        self.description = description
        self.tool_name = tool_name
        self.tool_description = tool_description
        self.design_notes = design_notes
        self.success_test = success_test
        self.priority = priority
        self.created_at = now().isoformat()

    def to_dict(self) -> dict:
        return {
            "capability_id": self.capability_id,
            "description": self.description,
            "tool_name": self.tool_name,
            "tool_description": self.tool_description,
            "design_notes": self.design_notes,
            "success_test": self.success_test,
            "priority": self.priority,
            "created_at": self.created_at,
        }


class StageResult:
    """Result from a pipeline stage."""

    def __init__(self, stage_name: str):
        self.stage_name = stage_name
        self.passed = False
        self.output = None
        self.error = None
        self.metadata: dict = {}
        self.started_at = now().isoformat()
        self.completed_at = None

    def complete(self, passed: bool, output=None, error=None, **metadata) -> "StageResult":
        self.passed = passed
        self.output = output
        self.error = error
        self.metadata = metadata
        self.completed_at = now().isoformat()
        return self

    def to_dict(self) -> dict:
        return {
            "stage": self.stage_name,
            "passed": self.passed,
            "output": str(self.output)[:500] if self.output else None,
            "error": self.error,
            "metadata": self.metadata,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class PipelineResult:
    """Complete result of a pipeline execution."""

    def __init__(self, spec: ImprovementSpec):
        self.spec = spec
        self.stages: list[StageResult] = []
        self.overall_passed = False
        self.summary = ""
        self.started_at = now().isoformat()
        self.completed_at = None

    def add_stage(self, stage: StageResult) -> None:
        self.stages.append(stage)

    def finalize(self) -> "PipelineResult":
        self.completed_at = now().isoformat()
        self.overall_passed = all(s.passed for s in self.stages)
        passed_count = sum(1 for s in self.stages if s.passed)
        self.summary = (
            f"Pipeline {'PASSED' if self.overall_passed else 'FAILED'}: "
            f"{passed_count}/{len(self.stages)} stages passed. "
            f"Capability: {self.spec.capability_id}"
        )
        return self

    def to_dict(self) -> dict:
        return {
            "spec": self.spec.to_dict(),
            "stages": [s.to_dict() for s in self.stages],
            "overall_passed": self.overall_passed,
            "summary": self.summary,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class SelfImprovementPipeline:
    """The 5-stage self-improvement pipeline.

    Stage 1: ANALYZE  — examine current state, identify gaps
    Stage 2: DESIGN   — create a specification for the improvement  
    Stage 3: FORGE    — create the tool code (via ToolForge with sandbox)
    Stage 4: VERIFY   — regression tests, integration checks
    Stage 5: REGISTER — register tool, update capability map, log completion
    """

    def __init__(self, tool_registry=None, tool_forge=None, capability_registry=None,
                 decision_log=None, memory=None, self_modify=None, reporter=None):
        self._tool_registry = tool_registry
        self._tool_forge = tool_forge
        self._capability_registry = capability_registry
        self._decision_log = decision_log
        self._memory = memory
        self._self_modify = self_modify
        self._reporter = reporter
        self._pipeline_history: list[PipelineResult] = []
        self._load_history()

    # ── Stage 1: ANALYZE ──────────────────────────────────────────────

    def analyze(self) -> StageResult:
        """Analyze current agent state and identify the highest-priority gap.
        
        Uses the CapabilityRegistry to assess all capabilities and find gaps.
        Returns the top recommendation as the analysis output.
        """
        stage = StageResult("analyze")

        if not self._capability_registry:
            return stage.complete(False, error="CapabilityRegistry not available.")

        try:
            gaps = self._capability_registry.assess_capabilities()
            
            if not gaps or not gaps.get("gaps"):
                return stage.complete(
                    True,
                    output={"action": "no_gaps", "message": "No capability gaps found."},
                )

            top_gap = gaps["gaps"][0]
            return stage.complete(
                True,
                output={
                    "capability_id": top_gap.get("capability_id", "unknown"),
                    "priority": top_gap.get("priority", "MEDIUM"),
                    "description": top_gap.get("description", ""),
                },
            )

        except Exception as e:
            return stage.complete(False, error=f"Analysis failed: {e}")

    # ── Stage 2: DESIGN ───────────────────────────────────────────────

    def design(self, analysis_output: dict) -> StageResult:
        """Design an improvement specification based on the analysis output.
        
        Creates an ImprovementSpec with tool_name, description, and design_notes.
        """
        stage = StageResult("design")

        if not analysis_output or analysis_output.get("action") == "no_gaps":
            return stage.complete(
                True,
                output={"action": "skip", "message": "No gaps to address."},
            )

        capability_id = analysis_output.get("capability_id", "unknown")
        description = analysis_output.get("description", "")
        priority = analysis_output.get("priority", "MEDIUM")

        if not description:
            return stage.complete(False, error="No description provided by analysis.")

        tool_name = self._capability_to_tool_name(capability_id)
        tool_description = f"Improves capability: {capability_id}"

        spec = ImprovementSpec(
            capability_id=capability_id,
            description=description,
            tool_name=tool_name,
            tool_description=tool_description,
            design_notes=f"Generated from analysis. Priority: {priority}",
            success_test="",
            priority=priority,
        )

        return stage.complete(True, output=spec)

    def _capability_to_tool_name(self, cap_id: str) -> str:
        """Convert capability ID to a tool name."""
        return cap_id.replace("_", "_")

    # ── Stage 3: FORGE ───────────────────────────────────────────────

    def forge(self, spec: ImprovementSpec, code: str = "", parameters: dict = None) -> StageResult:
        """Forge the tool using ToolForge (which includes ToolSandbox safety check).
        
        If code is provided, it's used directly. Otherwise, this stage requires
        external code generation (from LLM or other source).
        """
        valid, error_stage = self._validate_forge_inputs(code)
        if not valid:
            return error_stage
        return self._execute_forge(spec, code, parameters or {})

    def _validate_forge_inputs(self, code: str) -> tuple[bool, Optional[StageResult]]:
        """Validate forge stage inputs. Returns (valid, error_stage)."""
        if not self._tool_forge:
            return False, StageResult("forge").complete(
                False, error="ToolForge not available."
            )
        if not code:
            return False, StageResult("forge").complete(
                False,
                error="No code provided for forging. Code must be generated "
                      "externally (by LLM) and passed to this stage.",
                needs_code=True,
            )
        return True, None

    def _execute_forge(self, spec: ImprovementSpec, code: str, parameters: dict) -> StageResult:
        """Execute the forge stage."""
        stage = StageResult("forge")
        try:
            result = self._tool_forge.forge(
                name=spec.tool_name,
                description=spec.tool_description,
                code=code,
                parameters=parameters or {},
            )
            if result.get("success"):
                return stage.complete(
                    True,
                    output={
                        "tool_name": spec.tool_name,
                        "forge_result": result,
                        "sandbox_report": result.get("sandbox_report", ""),
                        "sandbox_warnings": result.get("sandbox_warnings", []),
                    },
                )
            else:
                return stage.complete(
                    False,
                    error=result.get("error", "Forge failed"),
                    forge_result=result,
                    sandbox_report=result.get("sandbox_report", ""),
                )
        except Exception as e:
            return stage.complete(False, error=f"Forge exception: {e}\n{traceback.format_exc()}")

    # ── Stage 4: VERIFY ────────────────────────────────────────────────

    def verify(self, spec: ImprovementSpec, forge_output: dict) -> StageResult:
        """Verify the forged tool works correctly.
        
        Checks:
        1. Tool is registered in the registry
        2. Tool can be called successfully
        3. Sandbox warnings review
        """
        stage = StageResult("verify")
        tool_name = spec.tool_name
        checks = {}

        # Check 1: Tool exists in registry
        found, error = self._check_tool_registry(tool_name)
        checks["registry_present"] = found
        if not found:
            return stage.complete(False, error=error, checks=checks)

        # Check 2: Tool can be invoked
        call_passed, call_checks = self._test_tool_call(tool_name)
        checks.update(call_checks)

        # Check 3: Sandbox warnings review
        checks.update(self._extract_sandbox_warnings(forge_output))

        all_passed = checks.get("registry_present", False) and checks.get("basic_call", True)
        return stage.complete(
            passed=all_passed,
            output={"tool_name": tool_name, "checks": checks, "all_passed": all_passed},
        )

    def _check_tool_registry(self, tool_name: str) -> tuple[bool, Optional[str]]:
        """Check if tool exists in registry. Returns (found, error)."""
        if self._tool_registry and self._tool_registry.has(tool_name):
            return True, None
        return False, f"Tool '{tool_name}' not found in registry after forge."

    def _test_tool_call(self, tool_name: str) -> tuple[bool, dict]:
        """Test calling the tool. Returns (passed, check_details)."""
        checks = {}
        try:
            if self._tool_registry:
                tool_info = self._tool_registry.list_tools().get(tool_name, {})
                params = tool_info.get("parameters", {})
                test_kwargs = self._build_test_args(params)
                raw_result = self._tool_registry.call(tool_name, **test_kwargs)
                if isinstance(raw_result, dict):
                    call_result = raw_result
                else:
                    call_result = {"success": bool(raw_result), "output": str(raw_result)}
                checks["basic_call"] = call_result.get("success", False)
                if not checks["basic_call"]:
                    checks["call_error"] = call_result.get("error", str(raw_result)[:100])
        except Exception as e:
            checks["basic_call"] = False
            checks["call_error"] = str(e)
        return checks.get("basic_call", False), checks

    def _extract_sandbox_warnings(self, forge_output: dict) -> dict:
        """Extract sandbox warnings from forge output."""
        checks = {}
        warnings = [w for w in forge_output.get("sandbox_warnings", []) 
                    if w.get("level") == "WARN"]
        checks["sandbox_warnings_count"] = len(warnings)
        if warnings:
            checks["sandbox_warnings_detail"] = [
                f"{w.get('type', '?')}: {w.get('detail', str(w))}" for w in warnings
            ]
        return checks

    def _build_test_args(self, parameters: dict) -> dict:
        """Build test arguments for tool invocation."""
        test_kwargs = {}
        if parameters:
            for param_name, param_info in parameters.items():
                param_type = param_info.get("type", "string")
                if param_type == "integer":
                    test_kwargs[param_name] = 0
                elif param_type == "array":
                    test_kwargs[param_name] = []
                elif param_type == "object":
                    test_kwargs[param_name] = {}
                else:
                    test_kwargs[param_name] = "test_value"
        return test_kwargs

    # ── Stage 5: REGISTER ──────────────────────────────────────────────

    def register_improvement(self, spec: ImprovementSpec, verify_output: dict) -> StageResult:
        """Register the improvement in the capability registry and log completion."""
        stage = StageResult("register")

        try:
            all_passed, checks = self._check_verification_passed(verify_output)
            if not all_passed:
                return stage.complete(False, error="Verification checks did not all pass.",
                                      verify_checks=checks)

            # Update capability registry
            self._record_capability_update(spec)

            # Log to decision log
            self._record_decision_log(spec)

            # Store pipeline result
            self._save_to_memory()

            # Generate evolution report + git commit/push
            report_result = self._generate_evolution_report(spec)

            return stage.complete(
                True,
                output={
                    "tool_name": spec.tool_name,
                    "capability_id": spec.capability_id,
                    "status": "registered",
                    "message": f"Capability '{spec.capability_id}' improved via tool '{spec.tool_name}'.",
                    "evolution_report": report_result,
                },
            )

        except Exception as e:
            return stage.complete(False, error=f"Register failed: {e}\n{traceback.format_exc()}")

    def _check_verification_passed(self, verify_output: dict) -> tuple[bool, dict]:
        """Check if verification passed. Returns (passed, checks)."""
        checks = verify_output.get("checks", {})
        all_passed = verify_output.get("all_passed", False)
        return all_passed, checks

    def _record_capability_update(self, spec: ImprovementSpec) -> None:
        """Update capability registry with new tool."""
        if self._capability_registry:
            self._capability_registry.record_improvement(
                capability_id=spec.capability_id,
                action=f"forged_tool:{spec.tool_name}",
                result=f"Pipeline completed. Tool '{spec.tool_name}' registered.",
            )

    def _record_decision_log(self, spec: ImprovementSpec) -> None:
        """Log pipeline completion to decision log."""
        if self._decision_log:
            self._decision_log.record(
                context={
                    "pipeline": "self_improvement",
                    "capability_id": spec.capability_id,
                    "tool_name": spec.tool_name,
                },
                decision_type="pipeline_complete",
                options_considered=[{"option": "register", "tool_name": spec.tool_name}],
                chosen_option=spec.tool_name,
                reasoning=f"Self-improvement pipeline completed for capability "
                          f"'{spec.capability_id}'. Tool '{spec.tool_name}' "
                          f"forged, verified, and registered.",
                expected_outcome=f"Capability '{spec.capability_id}' now covered.",
                phase="evolve",
            )

    def _generate_evolution_report(self, spec: ImprovementSpec) -> Optional[dict]:
        """Generate evolution report and commit. Returns report result or None."""
        if not self._reporter:
            return None
        changes = [{
            "type": "tool_forge",
            "description": f"Forged tool '{spec.tool_name}' for capability '{spec.capability_id}'",
            "detail": spec.description,
        }]
        try:
            return self._reporter.finalize_evolution(
                changes=changes,
                bump_type="patch",
                pipeline_result=None,
            )
        except Exception:
            return None

    # ── Pipeline Execution ───────────────────────────────────────────

    def run_full_pipeline(self, code: str = "", parameters: dict = None) -> PipelineResult:
        """Execute the full 5-stage pipeline.
        
        If code is provided, it will be used for the forge stage and 
        analyze+design stages are skipped (code contains spec inline).
        If not, the pipeline stops after design and returns the spec for external code generation.
        
        Returns a PipelineResult with all stage results.
        """
        if parameters is None:
            parameters = {}
        
        # FAST PATH: Code is provided → skip analyze+design, forge directly
        if code and code.strip():
            return self._run_forge_only(code, parameters)
        
        # FULL PATH: No code → analyze → design → (pause for code)
        result = self._execute_analyze_and_design()
        
        # Stage 3: Forge (requires code)
        if not result.stages[-1].passed or not code:
            return self._handle_forge_not_ready(result, code, parameters)
        
        return self._execute_pipeline_stages_345(result, code, parameters)

    def _execute_analyze_and_design(self) -> PipelineResult:
        """Execute stages 1 and 2: analyze and design."""
        stage1 = self.analyze()
        result = PipelineResult(ImprovementSpec("unknown", "Unknown"))
        result.add_stage(stage1)

        if not stage1.passed:
            return self._finalize_and_save(result)
        if stage1.output.get("action") == "no_gaps":
            result.summary = "No capability gaps to address."
            result.overall_passed = True
            return self._finalize_and_save(result)

        # Stage 2: Design
        stage2 = self.design(stage1.output)
        result.add_stage(stage2)
        result.spec = stage2.output if isinstance(stage2.output, ImprovementSpec) else result.spec
        return result

    def _handle_forge_not_ready(self, result: PipelineResult, code: str, parameters: dict) -> PipelineResult:
        """Handle case where forge stage cannot proceed."""
        if not result.stages[-1].passed:
            return self._finalize_and_save(result)
        
        # Design passed but no code provided
        result.add_stage(StageResult("forge").complete(
            False, error="No code provided. Pipeline paused after design stage.",
            needs_code=True,
        ))
        result.add_stage(StageResult("verify").complete(False, error="Skipped — forge stage not executed.", skipped=True))
        result.add_stage(StageResult("register").complete(False, error="Skipped — forge stage not executed.", skipped=True))
        result.finalize()
        result.spec = result.stages[1].output if isinstance(result.stages[1].output, ImprovementSpec) else result.spec
        return self._finalize_and_save(result)

    def _execute_pipeline_stages_345(self, result: PipelineResult, code: str, parameters: dict) -> PipelineResult:
        """Execute stages 3 (forge), 4 (verify), 5 (register)."""
        spec = result.spec

        stage3 = self.forge(spec, code, parameters)
        result.add_stage(stage3)
        if not stage3.passed:
            return self._finalize_and_save(result)

        stage4 = self.verify(spec, stage3.output)
        result.add_stage(stage4)
        if not stage4.passed:
            return self._finalize_and_save(result)

        stage5 = self.register_improvement(spec, stage4.output)
        result.add_stage(stage5)
        return self._finalize_and_save(result)

    def _run_forge_only(self, code: str, parameters: dict) -> PipelineResult:
        """Fast path: code is provided → skip analyze/design, forge directly."""
        spec = self._create_minimal_spec(code)
        result = PipelineResult(spec)
        
        # Add skipped analyze and design stages
        self._add_skipped_analyze_design(result)
        
        # Execute forge → verify → register
        stage3 = self.forge(spec, code, parameters)
        result.add_stage(stage3)
        if not stage3.passed:
            return self._finalize_and_save(result)
        
        stage4 = self.verify(spec, stage3.output)
        result.add_stage(stage4)
        if not stage4.passed:
            return self._finalize_and_save(result)
        
        stage5 = self.register_improvement(spec, stage4.output)
        result.add_stage(stage5)
        return self._finalize_and_save(result)

    def _create_minimal_spec(self, code: str) -> ImprovementSpec:
        """Extract minimal spec from provided code."""
        import re
        match = re.search(r'def\s+(\w+)\s*\(', code)
        tool_name = match.group(1) if match else "forged_tool"
        return ImprovementSpec(
            capability_id=tool_name,
            description="Directly forged from provided code.",
            tool_name=tool_name,
            tool_description=f"Forged tool: {tool_name}",
            success_test="",
        )

    # ── Pipeline Helpers ─────────────────────────────────────────────

    def _finalize_and_save(self, result: PipelineResult) -> PipelineResult:
        """Finalize result, append to history, and save to memory."""
        result.finalize()
        self._pipeline_history.append(result)
        self._save_to_memory()
        return result

    def _add_skipped_stage(self, result: PipelineResult, stage_name: str, reason: str) -> None:
        """Add a skipped stage to the pipeline result."""
        result.add_stage(StageResult(stage_name).complete(
            True,
            output={"action": "skipped", "message": reason},
            skipped=True,
        ))

    def _add_skipped_analyze_design(self, result: PipelineResult) -> None:
        """Add skipped analyze and design stages."""
        msg = "Skipped — code directly provided."
        self._add_skipped_stage(result, "analyze", msg)
        self._add_skipped_stage(result, "design", msg)

    # ── Pipeline Status & History ──────────────────────────────────────

    def get_last_result(self) -> Optional[PipelineResult]:
        """Get the most recent pipeline result."""
        if self._pipeline_history:
            return self._pipeline_history[-1]
        return None

    def get_history_summary(self) -> list[dict]:
        """Get summary of all pipeline executions."""
        return [r.to_dict() for r in self._pipeline_history[-10:]]

    def status_report(self) -> str:
        """Generate a status report of the pipeline."""
        lines = [
            f"SelfImprovementPipeline Status",
            f"  Total executions: {len(self._pipeline_history)}",
            f"  Last execution: {self._pipeline_history[-1].summary if self._pipeline_history else 'N/A'}",
        ]
        return "\n".join(lines)

    # ── Persistence ────────────────────────────────────────────────────

    def _save_to_memory(self) -> None:
        """Save pipeline history to memory."""
        if not self._memory:
            return
        try:
            history = [r.to_dict() for r in self._pipeline_history[-50:]]
            self._memory.store("pipeline_history", history)
        except Exception:
            pass

    def _load_history(self) -> None:
        """Load pipeline history from memory."""
        if not self._memory:
            return
        try:
            data = self._memory.get("pipeline_history")
            if data:
                # Reconstruct PipelineResults from stored data
                for item in data[-10:]:
                    spec = ImprovementSpec(
                        item["spec"]["capability_id"],
                        item["spec"]["description"],
                        tool_name=item["spec"].get("tool_name", ""),
                        tool_description=item["spec"].get("tool_description", ""),
                    )
                    result = PipelineResult(spec)
                    result.overall_passed = item.get("overall_passed", False)
                    result.summary = item.get("summary", "")
                    result.completed_at = item.get("completed_at")
                    self._pipeline_history.append(result)
        except Exception:
            pass
