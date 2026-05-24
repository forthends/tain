"""
Tool Sandbox — built-in safety validation for forged tools.

Validates agent-forged Python code before registration:
  - Syntax errors
  - Dangerous imports (os.system, subprocess with shell=True, etc.)
  - Workspace path escapes (writes outside agent_workspace/)
  - Exec-level exceptions from basic smoke test

This is a BUILT-IN tool — always available, not dependent on agent forging it.
"""

import ast
import re
import sys
import io
from pathlib import Path


# Dangerous patterns that should not appear in agent-forged tools
_DANGEROUS_PATTERNS = [
    (re.compile(r'os\.system\s*\('), 'os.system() call'),
    (re.compile(r'subprocess\.(call|run|Popen)\s*\([^)]*shell\s*=\s*True'), 'subprocess with shell=True'),
    (re.compile(r'__import__\s*\(\s*[\"\\\']os[\"\\\']'), 'dynamic os import'),
    (re.compile(r'eval\s*\('), 'eval() call'),
    (re.compile(r'exec\s*\('), 'exec() call (not compile)'),
    (re.compile(r'shutil\.rmtree'), 'shutil.rmtree'),
    (re.compile(r'os\.remove\s*\(|os\.unlink\s*\('), 'os.remove/os.unlink'),
    (re.compile(r'os\.rmdir\s*\(|os\.removedirs\s*\('), 'os.rmdir'),
]


def test_forged_tool(code: str, test_function: str = "main") -> dict:
    """Validate a forged tool for safety and basic correctness.

    Args:
        code: Python source code of the tool.
        test_function: Name of the primary function to test (default: "main").

    Returns:
        dict with keys: passed, summary, warnings, errors, functions_found
    """
    warnings = []
    errors = []
    functions_found = []

    # ── Stage 0: Syntax check ──
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {
            "passed": False,
            "summary": f"Syntax error: {e}",
            "warnings": [],
            "errors": [{"type": "syntax_error", "detail": str(e)}],
            "functions_found": [],
        }

    # ── Stage 1: Extract function names ──
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions_found.append(node.name)

    if not functions_found:
        return {
            "passed": False,
            "summary": "No function definitions found in code.",
            "warnings": [],
            "errors": [{"type": "no_functions", "detail": "Code must define at least one function."}],
            "functions_found": [],
        }

    # ── Stage 2: Scan for dangerous patterns ──
    for pattern, desc in _DANGEROUS_PATTERNS:
        if pattern.search(code):
            errors.append({
                "type": "dangerous_pattern",
                "detail": f"Dangerous pattern detected: {desc}",
            })

    # ── Stage 3: Workspace path escape check ──
    _check_path_escapes(code, warnings)

    # ── Stage 4: Compile and import check ──
    try:
        compiled = compile(code, f"<sandbox:{test_function}>", "exec")
    except Exception as e:
        errors.append({"type": "compile_error", "detail": str(e)})
        return {
            "passed": False,
            "summary": f"Compilation failed: {e}",
            "warnings": warnings,
            "errors": errors,
            "functions_found": functions_found,
        }

    # ── Stage 5: Basic exec smoke test ──
    ns = {}
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        exec(compiled, ns)
        # Check that the target function exists and is callable
        func = ns.get(test_function) or ns.get(functions_found[0])
        if func is None:
            errors.append({"type": "function_not_found",
                          "detail": f"Function '{test_function}' not found after exec."})
        elif not callable(func):
            errors.append({"type": "not_callable",
                          "detail": f"'{test_function}' is not callable."})
    except Exception as e:
        errors.append({"type": "exec_error", "detail": str(e)})
    finally:
        sys.stdout = old_stdout

    passed = len(errors) == 0
    return {
        "passed": passed,
        "summary": _build_summary(passed, functions_found, warnings, errors),
        "warnings": warnings,
        "errors": errors,
        "functions_found": functions_found,
    }


def _check_path_escapes(code: str, warnings: list) -> None:
    """Scan for file paths that may escape the agent workspace."""
    path_patterns = [
        (re.compile(r'["\'](/[^"\']+)["\']'), 'absolute'),
        (re.compile(r'["\'](\.\./[^"\']+)["\']'), 'parent-dir traversal'),
    ]
    for pattern, desc in path_patterns:
        for m in pattern.finditer(code):
            # Allow paths inside agent_workspace or __file__ based paths
            p = m.group(1)
            if 'agent_workspace' in p or '__file__' in p:
                continue
            warnings.append({
                "level": "WARN",
                "type": f"path_{desc}",
                "detail": f"Potential {desc} path: {p}",
            })


def _build_summary(passed: bool, functions: list[str],
                   warnings: list, errors: list) -> str:
    parts = []
    if passed:
        parts.append(f"PASSED: {len(functions)} function(s) found ({', '.join(functions[:5])})")
    else:
        parts.append(f"FAILED: {len(errors)} error(s)")
    if warnings:
        parts.append(f"{len(warnings)} warning(s)")
    return ". ".join(parts)
