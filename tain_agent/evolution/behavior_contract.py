"""
BehaviorContract — safety layer between LLM code generation and sandbox forging.

Every LLM-generated tool must declare its boundaries (imports, side effects,
runtime), and the contract is verified via AST analysis before the code enters
the sandbox.

The ``from_generated`` classmethod parses LLM output into a contract.
``verify_code_compliance`` walks the code's AST to check that every import
matches the declared side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Constants ────────────────────────────────────────────────────────────────

_VALID_EFFECTS: frozenset[str] = frozenset({
    "file_read", "file_write", "network", "subprocess", "none",
})

_MODULE_SIDE_EFFECT_MAP: dict[str, str] = {
    "urllib": "network", "http": "network", "httpx": "network",
    "requests": "network", "aiohttp": "network", "socket": "network",
    "ftplib": "network", "smtplib": "network",
    "pathlib": "file_read", "os": "file_write", "sys": "file_write",
    "shutil": "file_write", "io": "file_write", "csv": "file_read",
    "json": "file_read",
    "subprocess": "subprocess", "multiprocessing": "subprocess",
    "signal": "subprocess",
}

_ALWAYS_ALLOWED: frozenset[str] = frozenset({
    "math", "statistics", "random", "datetime", "collections",
    "itertools", "functools", "typing", "hashlib", "base64",
    "re", "string", "textwrap", "enum", "dataclasses", "uuid",
    "copy", "html", "xml", "argparse", "logging", "json",
})

# ── Exceptions ───────────────────────────────────────────────────────────────

class ContractValidationError(ValueError):
    """Raised when a contract JSON is malformed or contains invalid values."""

# ── Data types ───────────────────────────────────────────────────────────────

@dataclass
class ContractComplianceResult:
    """Result of verifying that generated code complies with its contract.

    Attributes:
        compliant: True when all imports match the declared side effects.
        violations: Human-readable descriptions of each violation found.
    """

    compliant: bool
    violations: list[str] = field(default_factory=list)


@dataclass
class BehaviorContract:
    """Declared boundaries for an LLM-generated tool.

    Attributes:
        tool_name: The function name this contract covers.
        input_schema: JSON Schema describing the tool's input parameters.
        output_schema: JSON Schema describing the tool's return value.
        side_effects: Declared side-effect categories (e.g. ``["network"]``).
        max_runtime_ms: Maximum allowed runtime in milliseconds.

    *Valid side effects* are ``"file_read", "file_write", "network",
    "subprocess", "none"``.  The default is ``["none"]`` (pure compute).

    *Default runtime* is 5000 ms when not specified by the LLM.
    """

    tool_name: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    side_effects: list[str] = field(default_factory=lambda: ["none"])
    max_runtime_ms: int = 5000

    # Class-level frozenset for convenience -- hidden from the dataclass ctor /
    # repr so it stays clean.
    _VALID_EFFECTS: frozenset[str] = field(
        default=_VALID_EFFECTS, init=False, repr=False,
    )

    # ── Factory ──────────────────────────────────────────────────────────

    @classmethod
    def from_generated(
        cls, tool_name: str, contract_json: dict[str, Any]
    ) -> BehaviorContract:
        """Parse LLM output into a validated ``BehaviorContract``.

        Parameters:
            tool_name: The name of the tool the contract covers.
            contract_json: Raw dict from the LLM.  Expected keys:
                ``input_schema``, ``output_schema``, ``side_effects``,
                ``max_runtime_ms``.  Missing keys get safe defaults.

        Returns:
            A fully validated ``BehaviorContract`` instance.

        Raises:
            ContractValidationError: When ``side_effects`` contains an invalid
                value.
        """
        side_effects: list[str] = contract_json.get("side_effects", ["none"])
        max_runtime_ms: int = contract_json.get("max_runtime_ms", 5000)
        input_schema: dict[str, Any] = contract_json.get("input_schema", {})
        output_schema: dict[str, Any] = contract_json.get("output_schema", {})

        # Validate side effects
        invalid = [se for se in side_effects if se not in _VALID_EFFECTS]
        if invalid:
            raise ContractValidationError(
                f"Invalid side effects: {sorted(invalid)}. "
                f"Allowed: {sorted(_VALID_EFFECTS)}"
            )

        return cls(
            tool_name=tool_name,
            input_schema=input_schema,
            output_schema=output_schema,
            side_effects=side_effects,
            max_runtime_ms=max_runtime_ms,
        )

    # ── Compliance verification ──────────────────────────────────────────

    def verify_code_compliance(self, code: str) -> ContractComplianceResult:
        """Check that *code* imports only modules matching ``self.side_effects``.

        Parses the code with :func:`ast.parse`, walks the AST, collects every
        ``import X`` and ``from X import ...`` node, extracts the top-level
        module name, and checks it against the declared side effects.

        * Modules in the always-allowed set (stdlib utilities) are silently
          skipped.
        * Unknown modules (not in the side-effect map) are silently skipped
          (the sandbox will catch them at runtime).
        * Every other module must map to a side effect listed in
          ``self.side_effects``.  If not, a violation is recorded.

        Parameters:
            code: The Python source to verify.

        Returns:
            A ``ContractComplianceResult`` where ``compliant`` is ``True`` only
            when no violations were found.
        """
        import ast

        violations: list[str] = []
        declared: set[str] = set(self.side_effects)

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return ContractComplianceResult(
                compliant=False,
                violations=[f"Syntax error in generated code: {exc}"],
            )

        for node in ast.walk(tree):
            module_name: str | None = None

            if isinstance(node, ast.Import):
                # "import a.b.c" → "a"
                for alias in node.names:
                    module_name = alias.name.split(".", 1)[0]
                    self._check_module(module_name, declared, violations)
                continue

            if isinstance(node, ast.ImportFrom):
                # "from a.b.c import d" → "a", but skip relative imports
                if node.module is not None and node.level == 0:
                    module_name = node.module.split(".", 1)[0]
                    self._check_module(module_name, declared, violations)

        return ContractComplianceResult(
            compliant=len(violations) == 0,
            violations=violations,
        )

    def _check_module(
        self,
        module_name: str,
        declared: set[str],
        violations: list[str],
    ) -> None:
        """Check a single top-level module name against the contract."""
        # Always-allowed modules are fine regardless of side effects.
        if module_name in _ALWAYS_ALLOWED:
            return

        # Look up the expected side effect for this module.
        expected: str | None = _MODULE_SIDE_EFFECT_MAP.get(module_name)
        if expected is None:
            # Not a known restricted module — let the sandbox handle it.
            return

        if expected not in declared:
            violations.append(
                f"Module '{module_name}' implies side effect '{expected}', "
                f"but contract for '{self.tool_name}' only declares "
                f"{sorted(declared)}. "
                f"Add '{expected}' to side_effects or remove the import."
            )
