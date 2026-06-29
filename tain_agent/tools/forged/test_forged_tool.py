"""
Tool Sandbox — AST-whitelist safety validation for forged tools.

Validates agent-forged Python code before registration using:
  - AST-based import whitelist (not regex)
  - AST-based call target resolution (handles aliased imports)
  - Subprocess isolation for smoke-test execution
  - Timeout protection

The regex-based approach was replaced because it is trivially bypassable
via string construction, getattr, encoding tricks, or indirect calls.
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from tain_agent.tools.sandbox_allowlist import SANDBOX_ALLOWED_MODULES as _ALLOWED_MODULES

from tain_agent.tools.sandbox_allowlist import (
    SANDBOX_BLACKLIST_CALLS as _BLACKLIST_CALLS,
    SANDBOX_BLACKLIST_MODULES as _BLACKLIST_MODULES,
)

# ── Sandbox execution timeout ──────────────────────────────────────────

_SANDBOX_TIMEOUT = 10  # seconds


# ── Public API ─────────────────────────────────────────────────────────

def test_forged_tool(code: str, test_function: str = "main") -> dict:
    """Validate a forged tool for safety and basic correctness.

    Args:
        code: Python source code of the tool.
        test_function: Name of the primary function to test (default: "main").

    Returns:
        dict with keys: passed, summary, warnings, errors, functions_found
    """
    warnings: list[dict] = []
    errors: list[dict] = []
    functions_found: list[str] = []

    # ── Stage 0: Syntax check ──────────────────────────────────────────
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

    # ── Stage 1: Extract function names ────────────────────────────────
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

    # ── Stage 2: Build import alias map ────────────────────────────────
    alias_map = _build_import_map(tree)

    # ── Stage 3: AST-based import whitelist check ──────────────────────
    _check_imports(tree, alias_map, errors)

    # ── Stage 4: AST-based call target check ───────────────────────────
    _check_calls(tree, alias_map, errors)

    # ── Stage 5: Workspace path escape check ───────────────────────────
    _check_path_escapes(tree, warnings)

    # ── Stage 6: Compile ───────────────────────────────────────────────
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

    # ── Stage 7: Subprocess smoke test ─────────────────────────────────
    smoke_result = _run_smoke_test(code, test_function, functions_found)
    if not smoke_result["passed"]:
        errors.extend(smoke_result.get("errors", []))

    passed = len(errors) == 0
    return {
        "passed": passed,
        "summary": _build_summary(passed, functions_found, warnings, errors),
        "warnings": warnings,
        "errors": errors,
        "functions_found": functions_found,
    }


# ── Import map builder ─────────────────────────────────────────────────

def _build_import_map(tree: ast.AST) -> dict[str, str]:
    """Build a mapping from local alias to full module name.

    Handles:
        import foo.bar as fb  →  fb → foo.bar
        from foo.bar import baz  →  baz → foo.bar.baz
        from foo import bar as b  →  b → foo.bar
    """
    alias_map: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name
                alias_map[name] = alias.name

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                name = alias.asname or alias.name
                alias_map[name] = f"{module}.{alias.name}" if module else alias.name

    return alias_map


# ── Import validator ───────────────────────────────────────────────────

def _check_imports(tree: ast.AST, alias_map: dict[str, str],
                   errors: list[dict]) -> None:
    """Validate all imports against the module whitelist."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".")[0]
                if top_level in _BLACKLIST_MODULES:
                    errors.append({
                        "type": "blocked_import",
                        "detail": f"Import of '{alias.name}' is blocked (module '{top_level}' not allowed).",
                    })
                elif top_level not in _ALLOWED_MODULES and "." not in alias.name:
                    errors.append({
                        "type": "unlisted_import",
                        "detail": f"Import of '{alias.name}' is not in allowed modules list.",
                    })

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            top_level = module.split(".")[0] if module else ""
            if top_level in _BLACKLIST_MODULES:
                names = ", ".join(a.name for a in node.names)
                errors.append({
                    "type": "blocked_import",
                    "detail": f"Import from '{module}' ({names}) is blocked (module '{top_level}' not allowed).",
                })
            elif top_level and top_level not in _ALLOWED_MODULES and "." not in module:
                names = ", ".join(a.name for a in node.names)
                errors.append({
                    "type": "unlisted_import",
                    "detail": f"Import from '{module}' ({names}) is not in allowed modules list.",
                })


# ── Call target validator ──────────────────────────────────────────────

def _check_calls(tree: ast.AST, alias_map: dict[str, str],
                 errors: list[dict]) -> None:
    """Validate function calls against the blacklist.

    Resolves call targets through the import alias map to catch
    indirect calls like `import os; os.system(...)` or
    `from os import system; system(...)`.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        target = _resolve_call_target(node.func, alias_map)
        if target is None:
            continue

        # Check builtin blacklist (eval, exec, compile, __import__)
        if target in _BLACKLIST_CALLS:
            errors.append({
                "type": "blocked_call",
                "detail": f"Call to '{target}()' is blocked.",
            })
            continue

        # Check module-scoped blacklist (os.system, subprocess.run, etc.)
        if "." in target:
            top_level = target.split(".")[0]
            if top_level in _BLACKLIST_MODULES:
                errors.append({
                    "type": "blocked_call",
                    "detail": f"Call to '{target}()' is blocked (module '{top_level}' not allowed).",
                })

        # Check for attribute access chains that resolve to dangerous modules
        # e.g., getattr(__builtins__, 'eval'), builtins.eval, etc.
        _check_attribute_chain(node.func, alias_map, errors)


def _resolve_call_target(func: ast.AST, alias_map: dict[str, str]) -> str | None:
    """Resolve a call target to its fully qualified name.

    Returns None if the target cannot be statically resolved
    (e.g., dynamic dispatch through a variable).
    """
    if isinstance(func, ast.Name):
        # Simple: eval(...)
        return func.id

    if isinstance(func, ast.Attribute):
        # Module.func or obj.method: os.system, pathlib.Path, etc.
        base = _resolve_attribute_base(func, alias_map)
        if base is not None:
            return f"{base}.{func.attr}"
        return func.attr  # Best-effort: just the method name

    return None


def _resolve_attribute_base(node: ast.Attribute,
                            alias_map: dict[str, str]) -> str | None:
    """Walk an attribute chain to resolve the base module.

    E.g., os.path.join → "os.path"
          my_module.MyClass.method → "my_module.MyClass"
    """
    parts: list[str] = []

    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value

    if isinstance(current, ast.Name):
        # Check if the root name is an import alias
        root = alias_map.get(current.id, current.id)
        parts.append(root)
        parts.reverse()
        return ".".join(parts)

    return None


def _check_attribute_chain(func: ast.AST, alias_map: dict[str, str],
                           errors: list[dict]) -> None:
    """Check for dangerous attribute access patterns like getattr(__builtins__, 'eval')."""
    if not isinstance(func, ast.Call):
        return

    inner_target = _resolve_call_target(func, alias_map)
    if inner_target in ("getattr", "hasattr", "setattr", "delattr"):
        # getattr with a dangerous target — flag it
        if len(func.args) >= 2 if hasattr(func, 'args') else False:
            # Check the module argument
            args = getattr(func, 'args', [])
            if len(args) >= 1:
                first_arg = args[0]
                if isinstance(first_arg, ast.Name):
                    resolved = alias_map.get(first_arg.id, first_arg.id)
                    top = resolved.split(".")[0]
                    if top in _BLACKLIST_MODULES:
                        errors.append({
                            "type": "blocked_call",
                            "detail": f"Dynamic attribute access targeting '{top}' is blocked.",
                        })


# ── Path escape checker (AST-based) ────────────────────────────────────

def _check_path_escapes(tree: ast.AST, warnings: list[dict]) -> None:
    """Scan AST for string constants that look like absolute paths or
    parent-directory traversals outside agent_workspace."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value: str = node.value
            # Absolute filesystem paths
            if value.startswith("/") and "agent_workspace" not in value:
                warnings.append({
                    "level": "WARN",
                    "type": "absolute_path",
                    "detail": f"Absolute path detected: {value}",
                })
            # Parent directory traversal
            elif value.startswith("../") and "agent_workspace" not in value:
                warnings.append({
                    "level": "WARN",
                    "type": "parent_dir_traversal",
                    "detail": f"Parent directory traversal: {value}",
                })


# ── Subprocess smoke test ──────────────────────────────────────────────

def _minimal_sandbox_env() -> dict[str, str]:
    """Return a minimal safe environment for sandbox subprocess execution.

    On Windows, preserves SystemRoot and SYSTEMDRIVE which are required
    for Python subprocess to start correctly. On Unix, uses a minimal
    PATH for security.
    """
    if os.name == "nt":
        env = {
            "PYTHONPATH": "",
            "PATH": os.environ.get("PATH", ""),
            "SystemRoot": os.environ.get("SystemRoot", "C:\\Windows"),
        }
        system_drive = os.environ.get("SYSTEMDRIVE", "C:")
        if system_drive:
            env["SYSTEMDRIVE"] = system_drive
        return env
    else:
        return {"PYTHONPATH": "", "PATH": "/usr/bin:/bin"}


def _run_smoke_test(code: str, test_function: str,
                    functions_found: list[str]) -> dict:
    """Execute the tool code in a subprocess for OS-level isolation.

    Returns {"passed": bool, "errors": [...]}.
    """
    func_to_test = test_function if test_function in functions_found else functions_found[0]

    # Build a self-contained test script that imports the tool and calls it
    test_script = f'''
import sys
import json
{code}

_result = None
_error = None
try:
    _func = {func_to_test}
    if callable(_func):
        import inspect
        _sig = inspect.signature(_func)
        if len(_sig.parameters) == 0:
            _result = _func()
        else:
            # Try with default args for simple cases
            _result = "callable-with-params"
    else:
        _error = "Function '{func_to_test}' is not callable"
except Exception as _e:
    _error = f"{{type(_e).__name__}}: {{_e}}"

print(json.dumps({{"result": str(_result) if _result is not None else None,
                   "error": _error}}))
'''

    try:
        proc = subprocess.run(
            [sys.executable, "-c", test_script],
            capture_output=True,
            text=True,
            timeout=_SANDBOX_TIMEOUT,
            env=_minimal_sandbox_env(),
        )

        if proc.returncode != 0:
            stderr_summary = proc.stderr.strip().split("\n")[-1] if proc.stderr.strip() else "Unknown error"
            return {
                "passed": False,
                "errors": [{"type": "subprocess_error",
                           "detail": f"Sandbox execution failed (exit {proc.returncode}): {stderr_summary}"}],
            }

        try:
            output = json.loads(proc.stdout.strip())
        except json.JSONDecodeError:
            return {
                "passed": False,
                "errors": [{"type": "subprocess_error",
                           "detail": "Sandbox produced invalid output."}],
            }

        if output.get("error"):
            return {
                "passed": False,
                "errors": [{"type": "exec_error", "detail": output["error"]}],
            }

        return {"passed": True, "errors": []}

    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "errors": [{"type": "timeout",
                       "detail": f"Sandbox execution exceeded {_SANDBOX_TIMEOUT}s timeout."}],
        }


# ── Summary builder ────────────────────────────────────────────────────

def _build_summary(passed: bool, functions: list[str],
                   warnings: list[dict], errors: list[dict]) -> str:
    parts: list[str] = []
    if passed:
        parts.append(f"PASSED: {len(functions)} function(s) found ({', '.join(functions[:5])})")
    else:
        parts.append(f"FAILED: {len(errors)} error(s)")
    if warnings:
        parts.append(f"{len(warnings)} warning(s)")
    return ". ".join(parts)
