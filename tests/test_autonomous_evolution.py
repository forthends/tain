"""Tests for the autonomous evolution loop — BehaviorContract and related types."""

from __future__ import annotations

import pytest

from tain_agent.evolution.behavior_contract import (
    BehaviorContract,
    ContractValidationError,
    ContractComplianceResult,
)


class TestBehaviorContract:
    """Unit tests for BehaviorContract — contract parsing, validation, and AST compliance."""

    def test_from_generated_parses_valid_contract(self):
        """from_generated() parses a valid contract JSON."""
        contract_json = {
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
            "output_schema": {"type": "object", "properties": {"result": {"type": "string"}}},
            "side_effects": ["none"],
            "max_runtime_ms": 3000,
        }
        contract = BehaviorContract.from_generated("search_tool", contract_json)
        assert contract.tool_name == "search_tool"
        assert contract.side_effects == ["none"]
        assert contract.max_runtime_ms == 3000
        assert contract.input_schema["type"] == "object"
        assert contract.output_schema["type"] == "object"

    def test_from_generated_rejects_invalid_side_effects(self):
        """from_generated() raises ContractValidationError for invalid side_effects."""
        contract_json = {
            "input_schema": {},
            "output_schema": {},
            "side_effects": ["eval_code", "unknown"],
            "max_runtime_ms": 1000,
        }
        with pytest.raises(ContractValidationError, match="Invalid side effects"):
            BehaviorContract.from_generated("bad_tool", contract_json)

    def test_from_generated_defaults_missing_fields(self):
        """from_generated() fills in safe defaults for missing optional fields."""
        contract_json = {}
        contract = BehaviorContract.from_generated("minimal_tool", contract_json)
        assert contract.side_effects == ["none"]
        assert contract.max_runtime_ms == 5000
        assert contract.input_schema == {}
        assert contract.output_schema == {}

    def test_code_compliance_passes_clean_code(self):
        """verify_code_compliance() passes for code using only stdlib."""
        contract = BehaviorContract(
            tool_name="math_tool", input_schema={}, output_schema={},
            side_effects=["none"], max_runtime_ms=1000,
        )
        code = '''"""A simple math tool."""
import json
import math
from collections import defaultdict

def math_tool(x: float) -> dict:
    """Compute square root."""
    return {"result": math.sqrt(x)}
'''
        result = contract.verify_code_compliance(code)
        assert result.compliant is True
        assert len(result.violations) == 0

    def test_code_compliance_detects_network_violation(self):
        """verify_code_compliance() flags import urllib when side_effects=['none']."""
        contract = BehaviorContract(
            tool_name="sneaky_tool", input_schema={}, output_schema={},
            side_effects=["none"], max_runtime_ms=1000,
        )
        code = '''"""Sneaky tool that imports network."""
import urllib.parse

def sneaky_tool(url: str) -> dict:
    return {"parsed": urllib.parse.urlparse(url)}
'''
        result = contract.verify_code_compliance(code)
        assert result.compliant is False
        assert len(result.violations) > 0
        assert any("urllib" in v for v in result.violations)

    def test_code_compliance_allows_declared_network(self):
        """verify_code_compliance() passes when side_effects match declared imports."""
        contract = BehaviorContract(
            tool_name="web_tool", input_schema={}, output_schema={},
            side_effects=["network"], max_runtime_ms=2000,
        )
        code = '''"""A web tool."""
import urllib.request
import json

def web_tool() -> dict:
    return {"status": "ok"}
'''
        result = contract.verify_code_compliance(code)
        assert result.compliant is True

    def test_code_compliance_detects_file_write_violation(self):
        """verify_code_compliance() flags 'import pathlib' when side_effects=['none']."""
        contract = BehaviorContract(
            tool_name="file_tool", input_schema={}, output_schema={},
            side_effects=["none"], max_runtime_ms=1000,
        )
        code = '''"""A tool that reads files."""
from pathlib import Path

def file_tool() -> dict:
    return {"files": []}
'''
        result = contract.verify_code_compliance(code)
        assert result.compliant is False
        assert any("pathlib" in v for v in result.violations)

    def test_code_compliance_allows_declared_file_read(self):
        """verify_code_compliance() passes when file_read is declared and pathlib is used."""
        contract = BehaviorContract(
            tool_name="reader_tool", input_schema={}, output_schema={},
            side_effects=["file_read"], max_runtime_ms=1000,
        )
        code = '''"""A file reading tool."""
from pathlib import Path

def reader_tool() -> dict:
    return {"path": str(Path.cwd())}
'''
        result = contract.verify_code_compliance(code)
        assert result.compliant is True

    def test_code_compliance_handles_syntax_error(self):
        """verify_code_compliance() returns non-compliant for unparseable code."""
        contract = BehaviorContract(
            tool_name="broken_tool", input_schema={}, output_schema={},
            side_effects=["none"], max_runtime_ms=1000,
        )
        code = 'def broken('  # SyntaxError
        result = contract.verify_code_compliance(code)
        assert result.compliant is False
        assert any("Syntax error" in v for v in result.violations)

    def test_code_compliance_detects_multiple_violations(self):
        """verify_code_compliance() reports all violations, not just the first."""
        contract = BehaviorContract(
            tool_name="multi_violation_tool", input_schema={}, output_schema={},
            side_effects=["none"], max_runtime_ms=1000,
        )
        code = '''"""A tool with multiple undeclared imports."""
import urllib.parse
from pathlib import Path
from http import client
'''
        result = contract.verify_code_compliance(code)
        assert result.compliant is False
        assert len(result.violations) >= 2
        assert any("urllib" in v for v in result.violations)
        assert any("pathlib" in v for v in result.violations)

    def test_code_compliance_allows_relative_imports(self):
        """verify_code_compliance() allows relative imports without violation."""
        contract = BehaviorContract(
            tool_name="relative_import_tool", input_schema={}, output_schema={},
            side_effects=["none"], max_runtime_ms=1000,
        )
        code = 'from .helper import do_stuff\ndef relative_import_tool() -> dict:\n    return do_stuff()\n'
        result = contract.verify_code_compliance(code)
        # Relative imports are an intentional escape hatch — should not trigger violations
        assert result.compliant is True
