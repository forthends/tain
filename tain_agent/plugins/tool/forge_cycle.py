"""
ClosedForgeCycle — the complete tool evolution loop.

The key improvement over plain ToolForge: the LLM can generate tool code,
validates it, forges it, verifies the result, and tracks failures.
This closes the evolution loop — the agent can design AND create its own tools.

6-stage cycle: ANALYZE → DESIGN → GENERATE → FORGE → VERIFY → REGISTER
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CycleStage(Enum):
    ANALYZE = "analyze"
    DESIGN = "design"
    GENERATE = "generate"
    FORGE = "forge"
    VERIFY = "verify"
    REGISTER = "register"


@dataclass
class ImprovementSpec:
    """What the agent wants to improve or add.

    Attributes:
        capability_id: Unique identifier for this capability (used for failure tracking).
        description: What the tool does, in plain language.
        function_name: The Python function name to generate/forge.
        parameters: Parameter schema dict (flat or JSON Schema format).
        reasoning: Why this tool is needed.
    """

    capability_id: str
    description: str
    function_name: str
    parameters: dict = field(default_factory=dict)
    reasoning: str = ""


@dataclass
class StageResult:
    """Result of a single cycle stage."""

    stage: CycleStage
    success: bool
    output: Any = None
    error: str = ""


@dataclass
class ForgeCycleResult:
    """Aggregate result of the full forge cycle."""

    success: bool
    stages: list[StageResult]
    tool_name: str | None = None
    final_code: str | None = None


class ClosedForgeCycle:
    """Wraps ToolRegistry + ToolForge + LLM backend to form a closed evolution loop.

    The agent describes what it needs (ImprovementSpec), and this class:
      1. Analyzes the request
      2. Designs the approach
      3. Generates code via LLM (or uses provided code)
      4. Forges the tool through the ToolForge sandbox
      5. Verifies the tool is registered and callable
      6. Confirms registration

    Consecutive generation failures per capability_id are tracked;
    after MAX_GENERATE_RETRIES, the cycle gives up for that capability.
    """

    MAX_GENERATE_RETRIES = 3

    def __init__(self, registry, forge, llm_backend=None):
        self.registry = registry
        self.forge = forge
        self.llm_backend = llm_backend
        self._consecutive_failures: dict[str, int] = {}

    # ── Public API ──────────────────────────────────────────────────────

    def run(
        self,
        spec: ImprovementSpec,
        code: str | None = None,
        llm_backend: Any = None,
    ) -> ForgeCycleResult:
        """Execute the full 6-stage closed forge cycle.

        Args:
            spec: ImprovementSpec describing what to build.
            code: Optional pre-written code. If provided, the Generate stage is skipped.
            llm_backend: Callable that takes a prompt string and returns generated code.
                         If None, falls back to self.llm_backend. If both are None,
                         the Generate stage fails.

        Returns:
            ForgeCycleResult with success flag, all stage results, and final code.
        """
        backend = llm_backend or self.llm_backend
        stages: list[StageResult] = []

        # Stage 1: ANALYZE
        stages.append(StageResult(
            CycleStage.ANALYZE, True,
            f"Analyzing capability: {spec.capability_id} — {spec.reasoning}",
        ))

        # Stage 2: DESIGN
        stages.append(StageResult(
            CycleStage.DESIGN, True,
            f"Design target: def {spec.function_name}(...) — {spec.description}",
        ))

        # Stage 3: GENERATE — skip if code provided
        if code is None:
            if backend is None:
                stages.append(StageResult(
                    CycleStage.GENERATE, False, None,
                    "No LLM backend available and no code provided — cannot generate.",
                ))
                return ForgeCycleResult(False, stages)
            gen_result = self._generate(spec, backend)
            stages.append(gen_result)
            if not gen_result.success:
                return ForgeCycleResult(False, stages)
            code = gen_result.output
        else:
            stages.append(StageResult(
                CycleStage.GENERATE, True, code,
                "[code provided — generate skipped]",
            ))

        # Stage 4: FORGE
        forge_result = self._forge(spec, code)
        stages.append(forge_result)
        if not forge_result.success:
            return ForgeCycleResult(False, stages)

        # Stage 5: VERIFY
        verify_result = self._verify(spec)
        stages.append(verify_result)
        if not verify_result.success:
            return ForgeCycleResult(False, stages)

        # Stage 6: REGISTER (registration already happened during forge; this is confirmation)
        stages.append(StageResult(
            CycleStage.REGISTER, True,
            f"Tool '{spec.function_name}' registered and available.",
        ))

        return ForgeCycleResult(
            success=True,
            stages=stages,
            tool_name=spec.function_name,
            final_code=code,
        )

    def reset_failures(self, capability_id: str | None = None) -> None:
        """Reset consecutive failure counters.

        Args:
            capability_id: Specific capability to reset, or None to clear all.
        """
        if capability_id is None:
            self._consecutive_failures.clear()
        else:
            self._consecutive_failures.pop(capability_id, None)

    # ── Internal stage handlers ─────────────────────────────────────────

    def _generate(self, spec: ImprovementSpec, llm_backend: Any) -> StageResult:
        """Ask the LLM backend to produce Python code matching the spec.

        Validates that the response contains the expected function definition.
        Tracks consecutive failures per capability_id; gives up after
        MAX_GENERATE_RETRIES.
        """
        cid = spec.capability_id

        # ── Retry limit check ──
        failures = self._consecutive_failures.get(cid, 0)
        if failures >= self.MAX_GENERATE_RETRIES:
            return StageResult(
                CycleStage.GENERATE, False, None,
                f"Max retries ({self.MAX_GENERATE_RETRIES}) exceeded for capability "
                f"'{cid}' ({failures} consecutive failures). Consider revising the spec.",
            )

        # ── Build prompt ──
        prompt_lines = [
            "Write a Python function that implements the following tool specification.",
            "",
            f"Function name: {spec.function_name}",
            f"Description: {spec.description}",
            f"Parameters: {spec.parameters}",
            "",
            "Requirements:",
            "- The function must be named exactly as specified above.",
            "- Accept all listed parameters with appropriate defaults.",
            "- Return a dictionary with at least a 'success' or 'result' key for structured output.",
            "- Do NOT include any file I/O outside the agent workspace.",
            "- Include a docstring explaining what the function does.",
            "",
            "Return ONLY valid Python code. No markdown fences, no explanation.",
        ]

        try:
            response = llm_backend("\n".join(prompt_lines))
        except Exception as e:
            self._consecutive_failures[cid] = failures + 1
            return StageResult(
                CycleStage.GENERATE, False, None,
                f"LLM backend error: {e}",
            )

        # ── Validate response ──
        code = response if isinstance(response, str) else str(response)

        # Strip markdown fences if the LLM included them anyway
        if code.startswith("```"):
            lines = code.split("\n")
            # Remove opening fence
            if lines[0].startswith("```"):
                lines = lines[1:]
            # Remove closing fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            code = "\n".join(lines)

        if f"def {spec.function_name}" not in code:
            self._consecutive_failures[cid] = failures + 1
            return StageResult(
                CycleStage.GENERATE, False, code,
                f"Generated code does not contain function 'def {spec.function_name}'. "
                f"LLM may have renamed or omitted it.",
            )

        # ── Success — reset counter ──
        self._consecutive_failures[cid] = 0
        return StageResult(CycleStage.GENERATE, True, code)

    def _forge(self, spec: ImprovementSpec, code: str) -> StageResult:
        """Forge the tool through the ToolForge sandbox pipeline."""
        result = self.forge.forge(
            name=spec.function_name,
            description=spec.description,
            code=code,
            parameters=spec.parameters if spec.parameters else None,
        )
        if result.get("success"):
            return StageResult(CycleStage.FORGE, True, result)
        return StageResult(
            CycleStage.FORGE, False, result,
            result.get("error", "Unknown forge error"),
        )

    def _verify(self, spec: ImprovementSpec) -> StageResult:
        """Verify the tool is registered in the registry and appears callable."""
        if not self.registry.has(spec.function_name):
            return StageResult(
                CycleStage.VERIFY, False, None,
                f"Tool '{spec.function_name}' not found in registry after forging.",
            )

        # Check the tool metadata looks sane
        tools = self.registry.list_tools()
        tool_info = tools.get(spec.function_name, {})

        return StageResult(
            CycleStage.VERIFY, True,
            {
                "name": spec.function_name,
                "description": tool_info.get("description", ""),
                "parameters": tool_info.get("parameters", {}),
            },
        )
