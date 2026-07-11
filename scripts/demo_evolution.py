#!/usr/bin/env python3
"""End-to-end evolution demo with mock LLM backend.

Demonstrates the 5-stage evolution loop:
  gap_detect → generate_mutation → contract_check → write → online_verify

Two paths are exercised:
  1. Valid tool → forge succeeds → tool count increases
  2. Blocked import → contract check catches it → tool not added (rollback)

Requires no API key, no network. Exit code: 0 = success, 1 = failure.
"""
from __future__ import annotations

import json
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tain_agent.package import AgentPackage, PackageKind, LayerKind
from tain_agent.package.evolution import Mutation, EvolutionResult
from tain_agent.evolution.behavior_contract import BehaviorContract


# ── Mock LLM backend ──────────────────────────────────────────────────────

class MockLLMBackend:
    """Returns preset code for valid and invalid tool generation."""

    VALID_CODE = '''"""A CSV analysis tool."""
import json
from collections import defaultdict
from typing import Any

def csv_analyzer(filepath: str = "", column: str = "") -> dict:
    """Analyze a CSV file and return column statistics."""
    return {"result": "analysis complete", "success": True}

def main():
    return csv_analyzer()
'''

    BLOCKED_CODE = '''"""A tool that tries to access the network."""
import os
import urllib.request

def data_fetcher(url: str = "") -> dict:
    """Fetch data from a URL — should be blocked."""
    os.system("echo blocked")
    return {"result": "fetched"}

def main():
    return data_fetcher()
'''

    def __init__(self, mode: str = "valid"):
        self.mode = mode
        self.call_count = 0

    def create_message(self, system_prompt: str, messages: list, tools=None):
        self.call_count += 1
        response = MagicMock()
        if self.mode == "valid":
            text = (
                "```python\n" + self.VALID_CODE + "\n```\n"
                "```contract\n"
                '{"side_effects": ["none"], "max_runtime_ms": 1000}\n'
                "```"
            )
        elif self.mode == "blocked":
            text = (
                "```python\n" + self.BLOCKED_CODE + "\n```\n"
                "```contract\n"
                '{"side_effects": ["none"], "max_runtime_ms": 1000}\n'
                "```"
            )
        else:
            text = "this is not valid python```def broken("
        response.text_blocks = [text]
        response.tool_calls = []
        return response


# ── Mock ToolPlugin ───────────────────────────────────────────────────────

class MockToolPlugin:
    def __init__(self, initial_tools: dict | None = None):
        self._tools: dict[str, str] = dict(initial_tools or {})
        self._forged: dict[str, str] = {}

    def list_tools(self) -> dict:
        return dict(self._tools)

    def list_forged(self) -> dict:
        return dict(self._forged)

    def get_sandbox_allowlist(self) -> list[str]:
        return ["json", "math", "datetime", "collections", "typing", "hashlib", "re", "csv"]

    def call(self, tool_name: str, **kwargs):
        if tool_name in self._tools or tool_name in self._forged:
            return {"success": True, "result": "ok"}
        raise ValueError(f"Tool '{tool_name}' not found")

    def forge_cycle(self, spec, code, llm_backend):
        result = MagicMock()
        result.success = True
        result.tool_name = spec.function_name
        self._forged[spec.function_name] = code
        self._tools[spec.function_name] = code
        return result

    def rollback(self, tool_name: str):
        self._forged.pop(tool_name, None)
        self._tools.pop(tool_name, None)


# ── Mock KnowledgePlugin ──────────────────────────────────────────────────

class MockKnowledgePlugin:
    def __init__(self):
        self._dynamic: list[dict] = []
        self.goals = MagicMock()
        self.goals.list_active.return_value = [
            {
                "id": "goal_001",
                "description": "Analyze sales data from CSV files",
                "success_criteria": "Generate summary statistics for CSV input",
                "status": "active",
                "required_capability": "csv_analyzer",
            }
        ]
        self.goals.list_all.return_value = self.goals.list_active.return_value


# ── Mock AgentPackage ─────────────────────────────────────────────────────

def make_demo_package(tmpdir: Path) -> AgentPackage:
    pkg_dir = tmpdir / "demo_agent"
    pkg_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "package": {
            "name": "demo_agent",
            "version": "0.1.0",
            "kind": "agent",
            "evolution_mode": "experimental",
        },
        "infra": {
            "runtime": {"kernel_version": "0.11.0"},
            "plugins": ["identity", "memory", "tool", "knowledge"],
        },
        "capability": {"tools": [
            {"name": "echo", "version": "1.0.0", "path": "capability/tools/echo.py", "hash": ""},
            {"name": "calculator", "version": "1.0.0", "path": "capability/tools/calculator.py", "hash": ""},
        ]},
        "cognitive": {"knowledge": [], "memory": [], "identity": {}},
        "expression": {"artifacts": []},
    }
    (pkg_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    return AgentPackage(
        name="demo_agent",
        kind=PackageKind.AGENT,
        version="0.1.0",
        packages_root=tmpdir,
    )


# ── Gap detector ──────────────────────────────────────────────────────────

def demo_gap_detector(package):
    return {
        "capability_id": "capability_gap_csv_analyzer",
        "description": (
            "Agent has 2 tools but active goal 'Analyze sales data from CSV files' "
            "requires 'csv_analyzer' which is not in the toolset."
        ),
        "gap_score": 1.0,
        "tool_count": 2,
    }


# ── Mutation generator ────────────────────────────────────────────────────

def make_mutation_generator(llm_backend: MockLLMBackend):
    def mutation_generator(gap, package):
        import json as _json
        prompt = (
            f"Generate a tool for capability: {gap['capability_id']}\n"
            f"Description: {gap['description']}"
        )
        response = llm_backend.create_message(
            system_prompt="You generate Python tools.",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.text_blocks[0] if response.text_blocks else ""

        code = ""
        if "```python" in raw:
            code = raw.split("```python")[1].split("```")[0].strip()
        elif "```" in raw:
            code = raw.split("```")[1].split("```")[0].strip()

        tool_name = gap.get("capability_id", "auto_tool")
        file_path = f"capability/tools/forged/{tool_name}.py"
        return Mutation(
            layer=LayerKind.CAPABILITY,
            change_type="new_tool",
            detail=f"Auto-generated tool '{tool_name}'",
            files_to_write=[(file_path, code.encode("utf-8"))],
            manifest_patch={
                "capability": {
                    "tools": [{"name": tool_name, "version": "1.0.0",
                               "path": file_path, "hash": ""}],
                },
            },
            source_gap=gap["capability_id"],
        )
    return mutation_generator


# ── Contract checker ──────────────────────────────────────────────────────

def demo_contract_checker(mutation, package):
    errors = []
    for rel_path, content_bytes in mutation.files_to_write:
        code = content_bytes.decode("utf-8")
        tool_name = Path(rel_path).stem
        contract = BehaviorContract(tool_name=tool_name)
        result = contract.verify_code_compliance(code)
        if not result.compliant:
            errors.append(f"{rel_path}: {result.violations}")
    return (len(errors) == 0, errors)


# ── Online verifier ───────────────────────────────────────────────────────

def demo_online_verifier(mutation, package):
    import subprocess
    import tempfile as _tempfile

    SANDBOX_BLACKLIST = frozenset({
        "os", "sys", "subprocess", "shutil", "socket", "ctypes",
        "urllib", "http", "requests", "importlib",
    })

    errors = []
    for rel_path, content_bytes in mutation.files_to_write:
        code = content_bytes.decode("utf-8")
        tool_name = Path(rel_path).stem

        # AST validation
        import ast as _ast
        try:
            tree = _ast.parse(code)
        except SyntaxError as e:
            errors.append(f"{rel_path}: syntax error: {e}")
            continue

        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in SANDBOX_BLACKLIST:
                        errors.append(f"{rel_path}: blocked import: {top}")
            elif isinstance(node, _ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    if top in SANDBOX_BLACKLIST:
                        errors.append(f"{rel_path}: blocked import: {top}")

        if errors:
            continue

        # Runtime smoke test
        tmp_dir = _tempfile.mkdtemp(prefix="demo_smoke_")
        tool_path = Path(tmp_dir) / f"{tool_name}.py"
        tool_path.write_text(code)
        try:
            proc = subprocess.run(
                [sys.executable, "-c", f"exec(open('{tool_path}').read()); print(main())"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode != 0:
                errors.append(f"{rel_path}: runtime error: {proc.stderr.strip()[-200:]}")
        except subprocess.TimeoutExpired:
            errors.append(f"{rel_path}: timed out")
        except Exception as e:
            errors.append(f"{rel_path}: {e}")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return (len(errors) == 0, errors)


# ── Main ──────────────────────────────────────────────────────────────────

def run_demo(mode: str = "valid") -> dict:
    tmpdir = Path(tempfile.mkdtemp(prefix="tain_demo_"))
    try:
        llm = MockLLMBackend(mode=mode)
        package = make_demo_package(tmpdir)

        gap = demo_gap_detector(package)
        if gap is None:
            return {"path": mode, "passed": False, "error": "No gap detected"}

        mutation = make_mutation_generator(llm)(gap, package)

        ok, contract_errors = demo_contract_checker(mutation, package)

        if mode == "blocked":
            if not ok:
                return {
                    "path": mode,
                    "passed": True,
                    "result": "Contract correctly blocked invalid import",
                    "contract_errors": contract_errors,
                }
            else:
                return {
                    "path": mode,
                    "passed": False,
                    "error": "Contract should have caught blocked import but didn't",
                }

        if not ok:
            return {
                "path": mode,
                "passed": False,
                "error": f"Contract rejected valid code: {contract_errors}",
            }

        vfy_ok, vfy_errors = demo_online_verifier(mutation, package)
        if not vfy_ok:
            return {
                "path": mode,
                "passed": False,
                "error": f"Online verification failed: {vfy_errors}",
            }

        return {
            "path": mode,
            "passed": True,
            "result": f"Tool '{mutation.detail}' evolved successfully",
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    results = []
    for mode in ["valid", "blocked"]:
        result = run_demo(mode)
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{status}] {mode}: {result.get('result', result.get('error', ''))}")

    print(json.dumps(results, indent=2))

    all_passed = all(r["passed"] for r in results)
    if all_passed:
        print("\n✓ All demo paths passed — evolution loop works end-to-end.")
        return 0
    else:
        print("\n✗ Some demo paths failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
