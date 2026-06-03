"""
Forge Cycle -- forging loop orchestrator

Orchestrates the full GENERATE -> FORGE -> INSTALL -> TEST -> REGISTER pipeline
for autonomous tool creation. Can be triggered by the improvement loop or
directly by the agent via run_forge_cycle tool.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ForgeResult:
    """Complete result of a forge cycle execution."""
    success: bool
    tool_name: str = ""
    stage_results: dict = field(default_factory=dict)
    code_generated: str = ""
    dependencies_installed: list[str] = field(default_factory=list)
    test_result: Optional[dict] = None
    registered: bool = False
    summary: str = ""


class ForgeCycle:
    """Orchestrates autonomous tool forging from gap detection to registration.

    Five stages:
      1. GENERATE -- call LLM to produce tool code + dependency declarations
      2. FORGE    -- ToolForge.forge() with ToolSandbox safety check
      3. INSTALL  -- DependencyManager.resolve() for required packages
      4. TEST     -- run_test in sandbox to verify tool correctness
      5. REGISTER -- update CapabilityRegistry, DecisionLog, LineageTracking
    """

    _MAX_FORGES_PER_SESSION = 3

    def __init__(self, tool_forge, dependency_manager, capability_registry,
                 decision_log, lineage_tracker, memory, llm_backend):
        self._tool_forge = tool_forge
        self._dependency_manager = dependency_manager
        self._capability_registry = capability_registry
        self._decision_log = decision_log
        self._lineage_tracker = lineage_tracker
        self._memory = memory
        self._llm_backend = llm_backend
        self._forge_count = 0
        self._max_forges = self._MAX_FORGES_PER_SESSION

    @property
    def remaining_quota(self) -> int:
        """Number of forge cycles remaining this session."""
        return max(0, self._max_forges - self._forge_count)

    def run(self, gap_spec: dict) -> ForgeResult:
        """Execute the complete forge cycle.

        Args:
            gap_spec: Dict with capability_id and description from gap analysis.

        Returns:
            ForgeResult with stage-by-stage results and overall status.
        """
        if self._forge_count >= self._max_forges:
            return ForgeResult(
                success=False,
                summary=f"Forge quota exhausted ({self._max_forges}/{self._max_forges}).",
                stage_results={"quota": {"passed": False, "output": None,
                                         "error": "Quota exhausted"}},
            )

        self._forge_count += 1
        result = ForgeResult(success=False, stage_results={})
        result.stage_results["generate"] = {"passed": False, "output": None, "error": None}

        # Stage 1: GENERATE
        gen_output = self._generate_code(gap_spec)
        result.stage_results["generate"]["output"] = gen_output
        if "error" in gen_output:
            result.stage_results["generate"]["error"] = gen_output["error"]
            result.summary = f"Generate failed: {gen_output['error']}"
            self._log_cycle(result)
            return result
        result.stage_results["generate"]["passed"] = True

        code = gen_output["code"]
        tool_name = gen_output.get("tool_name", gap_spec.get("capability_id", "forged_tool"))
        description = gen_output.get("description", gap_spec.get("description", ""))
        params = gen_output.get("parameters", {})
        deps = gen_output.get("dependencies", [])
        test_code = gen_output.get("test_code", "")
        result.tool_name = tool_name
        result.code_generated = code

        # Stage 2: FORGE
        forge_result = self._tool_forge.forge(tool_name, description, code, params)
        result.stage_results["forge"] = {
            "passed": forge_result.get("success", False),
            "output": forge_result,
            "error": forge_result.get("error") if not forge_result.get("success") else None,
        }
        if not forge_result.get("success"):
            result.summary = f"Forge rejected: {forge_result.get('error', 'Unknown')}"
            self._log_cycle(result)
            return result

        # Stage 3: INSTALL
        dep_result = self._dependency_manager.resolve(tool_name, deps)
        result.dependencies_installed = dep_result.installed
        rejected_msg = ""
        if dep_result.rejected:
            rejected_msg = f" ({len(dep_result.rejected)} packages rejected, applications filed)"
        result.stage_results["install"] = {
            "passed": True,
            "output": {"installed": dep_result.installed, "rejected": dep_result.rejected},
            "error": None,
        }

        # Stage 4: TEST
        test_result = self._run_test_in_sandbox(tool_name, test_code, "function")
        result.test_result = test_result
        result.stage_results["test"] = {
            "passed": test_result.get("passed", False),
            "output": test_result,
            "error": test_result.get("errors") if not test_result.get("passed") else None,
        }
        if not test_result.get("passed"):
            result.summary = f"Test failed: {test_result.get('errors', 'Unknown')}{rejected_msg}"
            self._log_cycle(result)
            return result

        # Stage 5: REGISTER
        try:
            self._capability_registry.record_improvement(
                capability_id=gap_spec.get("capability_id", tool_name),
                action=f"forged_tool:{tool_name}",
                result=f"ForgeCycle completed. Tool '{tool_name}' registered.",
            )
            if self._lineage_tracker:
                self._lineage_tracker.record_forge(
                    tool_name=tool_name,
                    tool_code=code,
                    agent_version=self._get_version(),
                    reasoning=f"Auto-forged via ForgeCycle: {description[:100]}",
                )
            result.registered = True
            result.stage_results["register"] = {"passed": True, "output": "registered", "error": None}
            result.success = True
            result.summary = f"Tool '{tool_name}' forged, tested, and registered.{rejected_msg}"
        except Exception as e:
            result.stage_results["register"] = {"passed": False, "output": None, "error": str(e)}
            result.summary = f"Register failed: {e}{rejected_msg}"

        self._log_cycle(result)
        return result

    def _generate_code(self, gap_spec: dict) -> dict:
        """Call LLM backend to generate tool code from a gap specification.

        Returns dict with code, tool_name, description, parameters, dependencies,
        test_code, or {"error": "..."} on failure.
        """
        if not self._llm_backend:
            return {"error": "No LLM backend available for code generation."}

        capability_id = gap_spec.get("capability_id", "unknown")
        description = gap_spec.get("description", "")

        prompt = (
            f"You are generating Python tool code for a self-evolving agent.\n\n"
            f"Capability needed: {capability_id}\n"
            f"Description: {description}\n\n"
            f"Generate a complete Python function that implements this capability.\n"
            f"The code will run in a sandbox with limited imports (stdlib whitelist "
            f"plus any packages the agent declares as dependencies).\n\n"
            f"Return a JSON object with these keys:\n"
            f'  "code": The complete Python function as a string.\n'
            f'  "tool_name": A snake_case name for the tool.\n'
            f'  "description": What the tool does (one line).\n'
            f'  "parameters": JSON Schema for the function parameters.\n'
            f'  "dependencies": List of pip package specs needed (e.g. ["requests"]).\n'
            f'  "test_code": A short assertion to verify the tool works.\n'
        )

        import json as _json
        try:
            response = self._llm_backend.create_message(
                system_prompt="You are a Python code generator for agent tools.",
                messages=[{"role": "user", "content": prompt}],
                tools=[],
            )
            text = "\n".join(response.text_blocks) if hasattr(response, 'text_blocks') else str(response)
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            return _json.loads(text.strip())
        except Exception as e:
            return {"error": f"Code generation failed: {e}"}

    def _run_test_in_sandbox(self, tool_name: str, test_code: str,
                             test_type: str = "function") -> dict:
        """Run the test in the sandbox environment."""
        if not test_code:
            test_code = (
                f"from tain_agent.tools.forged.{tool_name} import main\n"
                f"result = main()\n"
                f"print(result)"
            )
        try:
            from tain_agent.tools.primal import run_test as _run_test
            return _run_test(test_target=tool_name, test_type=test_type,
                             test_code=test_code)
        except Exception as e:
            return {"passed": False, "total": 1, "failures": 1,
                    "errors": f"run_test unavailable: {e}", "output": ""}

    def _get_version(self) -> str:
        """Get current framework version."""
        try:
            from tain_agent import __version__
            return __version__
        except ImportError:
            return "0.6.0"

    def _log_cycle(self, result: ForgeResult) -> None:
        """Record forge cycle outcome in decision log."""
        if not self._decision_log:
            return
        try:
            self._decision_log.record(
                context={"action": "forge_cycle", "tool_name": result.tool_name},
                decision_type="forge_cycle",
                options_considered=[{"option": "run_forge_cycle",
                                     "tool_name": result.tool_name}],
                chosen_option=result.tool_name if result.success else "abort",
                reasoning=f"ForgeCycle #{self._forge_count}: "
                          f"{'REGISTERED' if result.registered else 'FAILED'}. "
                          f"{result.summary}",
                expected_outcome=result.summary,
                phase="evolve",
            )
        except Exception:
            pass
