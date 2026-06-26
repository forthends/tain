"""
Tool Forge — 工具锻造

The agent's ability to create new tools for itself.
This is "二生三" — from self-awareness comes the ability to shape one's own capabilities.

The forge allows the agent to:
1. Design a new tool (describe what it does)
2. Implement it (write Python code)
3. Test it in the ToolSandbox (safety validation)
4. Register it (add to the tool registry for immediate use)
5. Modify or remove it (iterate)

Safety pipeline: NameCheck → ToolSandbox → Compile → Exec → Register
Both forge() and load_forged_tools() pass through the ToolSandbox gate.

Persistence: each tool saves its code (.py) and metadata (.meta.json) side-by-side.
On restart, parameters schema is fully restored.
"""

import json
import inspect
import traceback
from datetime import datetime, timezone
from pathlib import Path


def _build_skill_md(name: str, description: str, parameters: dict, code: str) -> str:
    """Build a SKILL.md file for a forged tool.

    Format follows the Claude Skills SKILL.md convention:
    YAML frontmatter for metadata, markdown body for documentation.
    """
    params_yaml = ""
    if parameters:
        props = parameters.get("properties", parameters)
        if isinstance(props, dict):
            for pname, pmeta in props.items():
                if isinstance(pmeta, dict):
                    ptype = pmeta.get("type", "string")
                    pdesc = pmeta.get("description", "")
                    params_yaml += f"  - name: {pname}\n"
                    params_yaml += f"    type: {ptype}\n"
                    params_yaml += f"    description: {pdesc}\n"

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return f"""---
name: {name}
description: {description}
version: 1.0.0
created: {now_iso}
dependencies: []
parameters:
{params_yaml if params_yaml else '  []'}
---

# {name}

## Description

{description}

## Usage

This skill was forged by a Tain Agent. It provides the `{name}` tool.

## Parameters

{_format_params_md(parameters)}

## Script

The implementation is in `scripts/{name}.py`.
"""


def _format_params_md(parameters: dict) -> str:
    """Format parameters as markdown table rows."""
    if not parameters:
        return "No parameters."
    props = parameters.get("properties", parameters)
    if not isinstance(props, dict) or not props:
        return "No parameters."

    lines = ["| Parameter | Type | Description |", "|-----------|------|-------------|"]
    for pname, pmeta in props.items():
        if isinstance(pmeta, dict):
            ptype = pmeta.get("type", "string")
            pdesc = pmeta.get("description", "")
            lines.append(f"| `{pname}` | {ptype} | {pdesc} |")
        else:
            lines.append(f"| `{pname}` | string | {pmeta} |")
    return "\n".join(lines)


class ToolForge:
    """The agent's workshop for creating, testing, and modifying tools.

    Safety: every forged tool MUST pass through the ToolSandbox before registration.
    This applies to both online forging (forge) and restart loading (load_forged_tools).
    This is the security gate for responsible recursive self-improvement.
    """

    def __init__(self, registry, decision_log=None, workspace_dir: str = None):
        self.registry = registry
        self.decision_log = decision_log
        self._forged_tools: dict[str, dict] = {}  # track forged tools
        ws = Path(workspace_dir) if workspace_dir else Path("agent_workspace")
        self._forge_dir = ws / "forged_tools"
        self._forge_dir.mkdir(parents=True, exist_ok=True)
        self._sandbox = None  # Lazy-loaded sandbox

    # ── Sandbox integration ───────────────────────────────────────────

    def _get_sandbox(self):
        """Lazy-load the ToolSandbox for safety testing."""
        if self._sandbox is not None:
            return self._sandbox
        try:
            from tain_agent.tools.forged.test_forged_tool import test_forged_tool
            self._sandbox = test_forged_tool
            return self._sandbox
        except ImportError:
            return None

    def _run_sandbox_check(self, name: str, code: str) -> dict:
        """Run the tool code through the ToolSandbox.

        Returns:
            {"passed": bool, "report": str, "warnings": list, "errors": list,
             "functions_found": list, "sandbox_result": dict}
        """
        sandbox_func = self._get_sandbox()
        if sandbox_func is None:
            return {
                "passed": False,
                "report": "Sandbox unavailable — refusing to forge tool without safety check.",
                "warnings": [{"level": "CRITICAL", "type": "sandbox_unavailable",
                              "detail": "ToolSandbox module could not be loaded. "
                                        "Tool forging is disabled for safety."}],
                "errors": [{"type": "sandbox_unavailable",
                           "detail": "Cannot verify tool safety. Refusing to forge."}],
                "functions_found": [],
                "sandbox_result": None,
            }

        try:
            result = sandbox_func(code=code, test_function=name)
            # Handle both dict and JSON string returns
            if isinstance(result, dict):
                report = result
            else:
                report = json.loads(result)
            sandbox_report = {
                "passed": report.get("passed", False),
                "report": report.get("summary", "No summary."),
                "warnings": report.get("warnings", []),
                "errors": report.get("errors", []),
                "functions_found": report.get("functions_found", []),
                "sandbox_result": report,
            }
            if not sandbox_report["passed"]:
                from tain_agent.tools.sandbox_allowlist import get_allowlist
                sandbox_report["allowlist_hint"] = get_allowlist()
            return sandbox_report
        except Exception as e:
            try:
                from tain_agent.tools.sandbox_allowlist import get_allowlist
                hint = get_allowlist()
            except Exception:
                hint = None
            return {
                "passed": False,
                "report": f"Sandbox internal error: {e}",
                "warnings": [],
                "errors": [{"type": "sandbox_error", "detail": str(e)}],
                "functions_found": [],
                "sandbox_result": None,
                "allowlist_hint": hint,
            }

    # ── Parameter inference from function signatures ──────────────────

    def _infer_parameters(self, func) -> dict:
        """Extract parameter schema from a function's type hints and signature."""
        try:
            sig = inspect.signature(func)
        except (ValueError, TypeError):
            return {}

        params = {}
        for pname, param in sig.parameters.items():
            if pname in ('self', 'cls'):
                continue
            annotation = param.annotation
            type_name = "string"
            if annotation is not inspect.Parameter.empty:
                if annotation is int:
                    type_name = "integer"
                elif annotation is float:
                    type_name = "number"
                elif annotation is bool:
                    type_name = "boolean"
                elif annotation is str:
                    type_name = "string"
                elif annotation is dict:
                    type_name = "object"
                elif annotation is list:
                    type_name = "array"
                elif hasattr(annotation, '__name__'):
                    type_name = "string"
                else:
                    type_name = "string"

            param_info = {
                "type": type_name,
                "description": f"Parameter: {pname}",
                "required": param.default is inspect.Parameter.empty,
            }
            if param.default is not inspect.Parameter.empty:
                param_info["default"] = repr(param.default)
            params[pname] = param_info
        return params

    # ── Forge ─────────────────────────────────────────────────────────

    # ── Forge helper: Stage 0 ──
    def _forge_check_name(self, name: str, action: str = "create") -> dict | None:
        """Check if name is protected, already exists, or doesn't exist (update mode).
        Returns error dict or None.

        For action="create" (default): rejects if the name already exists.
        For action="update": rejects if the name does NOT exist in the registry.
        """
        protected = {"observe_environment", "execute_code", "write_file", "read_file",
                     "web_fetch", "web_search", "get_current_time", "explore_directory"}
        if name in protected:
            return {"success": False, "error": f"Cannot override protected tool: {name}."}

        # ── Update mode: reject if tool does NOT exist ──
        if action == "update":
            if name not in self.registry.list_names():
                return {
                    "success": False,
                    "error": f"Tool '{name}' does not exist in registry. Cannot update a non-existent tool.",
                    "hint": "Use action='create' to forge a new tool with this name.",
                }
            return None

        # ── Create mode (default): reject if tool already exists ──
        if name in self.registry.list_names():
            return {
                "success": False,
                "error": f"Tool '{name}' already exists. Use a different name, remove the existing tool first, "
                         f"or use action='update' to modify it.",
                "hint": "Check /tools list to see all registered tools. To modify this tool, pass action='update'.",
            }
        # Check for similar names (fuzzy match)
        import difflib
        existing = self.registry.list_names() + list(self._forged_tools.keys())
        for ename in existing:
            if difflib.SequenceMatcher(None, name.lower(), ename.lower()).ratio() > 0.80:
                return {
                    "success": False,
                    "error": f"Similar tool already exists: '{ename}' (name similarity > 80%). "
                             f"Use a more distinctive name or check if the existing tool covers your needs.",
                }
        return None

    # ── Forge helper: Stage 1 ──
    def _forge_validate_sandbox(self, name: str, code: str) -> dict | None:
        """Run sandbox validation. Returns error dict or sandbox_result."""
        sr = self._run_sandbox_check(name, code)
        if not sr.get("passed", False):
            return {"success": False, "error": f"ToolSandbox rejected '{name}'.",
                    "sandbox_report": sr.get("report", "No report."),
                    "warnings": sr.get("warnings", [])}
        return sr

    # ── Forge helper: Stage 1.5 workspace path validation ──
    def _validate_workspace_paths(self, code: str) -> list[str]:
        """Scan code for file I/O patterns that escape the agent workspace.

        Detects hardcoded relative paths like 'knowledge/...', 'data/...'
        that would resolve relative to CWD instead of agent_workspace/.

        Returns a list of violation descriptions (empty = clean).
        """
        import re as _re
        violations = []

        # Patterns that indicate file writes with hardcoded relative paths.
        # Matches: open("relative/path", "w"/"a"), Path("relative/path"),
        # VARIABLE = "relative/path" style constants for jsonl/txt/csv files
        write_patterns = [
            (_re.compile(r'open\s*\(\s*["\']([^"\']+)["\']'), 'open()'),
            (_re.compile(r'(?:Path|pathlib\.Path)\s*\(\s*["\']([^"\']+)["\']'), 'Path()'),
        ]

        # Variable assignments that hardcode relative data paths
        var_path_pattern = _re.compile(
            r'(?:PATH|DIR|FILE|LOG|OUTPUT|JOURNAL|EXPLORATION)\w*\s*=\s*["\']([^"\']+\.(?:jsonl?|txt|csv|log|yaml|yml))["\']',
        )

        ws = str(self._forge_dir.parent.resolve())

        for pattern, desc in write_patterns:
            for m in pattern.finditer(code):
                path = m.group(1)
                if path.startswith(('/', '~', '\\\\', 'C:')):
                    # Absolute path — always a violation
                    violations.append(
                        f"Absolute path '{path}' in {desc} — must use workspace-relative path"
                    )
                elif not path.startswith(('agent_workspace/', 'agent_workspace\\')):
                    # Relative path not rooted in workspace — likely escape
                    if '/' in path or '\\' in path or '.' in path:
                        violations.append(
                            f"Relative path '{path}' in {desc} — may escape agent workspace. "
                            f"Use resolve_storage_path(content_type, filename) to get the canonical workspace path."
                        )

        for m in var_path_pattern.finditer(code):
            path = m.group(1)
            if not path.startswith(('agent_workspace/', 'agent_workspace\\',
                                   '{', '$', 'os.path', 'pathlib')):
                    violations.append(
                        f"Hardcoded data path '{path}' — use resolve_storage_path() "
                        f"to get the canonical path for your content type "
                        f"(e.g. resolve_storage_path('knowledge', '{path}')). "
                        f"Do not invent ad-hoc directory names."
                    )

        return violations

    # ── Forge helper: log warnings ──
    def _forge_log_warnings(self, name: str, warnings: list) -> None:
        if not self.decision_log or not warnings: return
        d = [f"{w.get('level','?')}: {w.get('detail',str(w))}" for w in warnings]
        self.decision_log.record(
            context={"action": "forge_tool_sandbox_warnings", "tool_name": name},
            decision_type="tool_forge",
            options_considered=[{"option": "proceed_with_warnings", "tool_name": name}],
            chosen_option=name,
            reasoning=f"Sandbox warnings: {'; '.join(d)}",
            expected_outcome=f"Tool '{name}' registered with warnings.",
            phase="evolve")

    # ── Forge helper: Stage 2+3 ──
    def _forge_compile_exec(self, name: str, code: str) -> dict:
        try: compiled = compile(code, f"<forged:{name}>", "exec")
        except SyntaxError as e: return {"success": False, "error": f"Syntax error: {e}"}
        ns = {"__file__": str(self._forge_dir / f"{name}.py")}
        try: exec(compiled, ns)
        except Exception as e: return {"success": False, "error": f"Exec error: {e}"}
        return ns

    # ── Forge helper: Stage 4 ──
    def _forge_discover_func(self, namespace: dict, name: str):
        candidates = {k: v for k, v in namespace.items()
                      if callable(v) and not k.startswith("_") and not isinstance(v, type)}
        if not candidates: return {"success": False, "error": "No callable function found."}
        return candidates.get("main") or candidates.get(name) or \
               max(candidates.items(), key=lambda kv: len(inspect.signature(kv[1]).parameters))[1]

    # ── Forge helper: Stage 5 ──
    def _forge_register(self, name: str, func, description: str, parameters: dict, code: str,
                        action: str = "create") -> None:
        # For update: remove old registration before re-registering
        if action == "update":
            self.registry.remove(name)
            self._forged_tools.pop(name, None)
        self.registry.register(name, func, description, parameters)
        self._forged_tools[name] = {"description": description, "code": code, "parameters": parameters}
        self._save_forged_tool(name, code, description, parameters, action=action)
        if self.decision_log:
            log_action = "forge_tool_updated" if action == "update" else "forge_tool"
            self.decision_log.record(
                context={"action": log_action, "tool_name": name},
                decision_type="tool_forge",
                options_considered=[{"option": action, "tool_name": name}],
                chosen_option=name,
                reasoning=f"Tool {action}d: {name} — {description}",
                expected_outcome=f"Tool '{name}' available.",
                phase="evolve")

    def forge(self, name: str, description: str, code: str, parameters: dict = None,
              action: str = "create") -> dict:
        """Dynamically create or update a tool from source code.
        Pipeline: NameCheck → Sandbox → PathCheck → Compile → Exec → Discover → Register

        Args:
            action: "create" (default) to forge a new tool, "update" to modify an existing one.
        """
        # Validate action
        if action not in ("create", "update"):
            return {
                "success": False,
                "error": f"Invalid action '{action}'. Must be 'create' or 'update'.",
            }
        # Stage 0
        err = self._forge_check_name(name, action=action)
        if err: return err
        # Stage 1
        sr = self._forge_validate_sandbox(name, code)
        if not isinstance(sr, dict) or sr.get("success") is False:
            return sr
        self._forge_log_warnings(name, sr.get("warnings", []))
        # Stage 1.5 — workspace path validation
        path_violations = self._validate_workspace_paths(code)
        if path_violations:
            return {
                "success": False,
                "error": f"Tool '{name}' contains file paths that may escape the agent workspace.",
                "path_violations": path_violations,
                "hint": (
                    "Use agent_workspace/-rooted paths (e.g. 'agent_workspace/knowledge/data.jsonl') "
                    "or compute paths from __file__: "
                    "str(pathlib.Path(__file__).resolve().parent.parent / 'knowledge' / 'data.jsonl')"
                ),
            }
        # Stage 2-3
        ns = self._forge_compile_exec(name, code)
        if isinstance(ns, dict) and ns.get("success") is False: return ns
        # Stage 4
        func = self._forge_discover_func(ns, name)
        if isinstance(func, dict): return func
        # Stage 4.5
        if not parameters: parameters = self._infer_parameters(func)
        # Stage 5
        self._forge_register(name, func, description, parameters, code, action=action)
        return {"success": True,
                "message": f"Tool '{name}' forged and registered successfully.",
                "tool_description": description, "tool_parameters": parameters,
                "sandbox_passed": True, "sandbox_report": sr.get("report", "No report."),
                "sandbox_warnings": sr.get("warnings", [])}

    # ── Skill export ────────────────────────────────────────────────────

    def export_as_skill(self, name: str) -> dict:
        """Export a forged tool as a SKILL.md-compliant skill package.

        Creates a self-contained directory structure:
            forged_tools/skills/{name}/
            ├── SKILL.md          # YAML frontmatter + markdown body
            ├── scripts/
            │   └── {name}.py     # tool source code
            ├── references/        # reference materials (empty)
            └── assets/            # output templates (empty)

        Returns:
            dict with skill_path and status.
        """
        source_path = self._forge_dir / f"{name}.py"
        meta_path = self._forge_dir / f"{name}.meta.json"

        if not source_path.exists():
            return {"success": False, "error": f"Tool '{name}' not found in forge."}

        code = source_path.read_text(encoding="utf-8")
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError):
                pass

        skill_dir = self._forge_dir / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "scripts").mkdir(exist_ok=True)
        (skill_dir / "references").mkdir(exist_ok=True)
        (skill_dir / "assets").mkdir(exist_ok=True)

        # Build SKILL.md
        description = meta.get("description", f"Tool: {name}")
        parameters = meta.get("parameters", {})
        created = meta.get("created", _now_iso() if '_now_iso' in dir() else '')

        skill_md = _build_skill_md(
            name=name,
            description=description,
            parameters=parameters,
            code=code,
        )
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

        # Copy source
        (skill_dir / "scripts" / f"{name}.py").write_text(code, encoding="utf-8")

        return {
            "success": True,
            "skill_path": str(skill_dir),
            "message": f"Skill '{name}' exported to {skill_dir}",
        }

    # ── Persistence ───────────────────────────────────────────────────

    def _save_forged_tool(self, name: str, code: str, description: str = "",
                         parameters: dict = None, action: str = "create") -> None:
        """Persist forged tool source code + metadata to disk.

        Safety: checks for file collisions before overwriting. If {name}.py already exists
        and contains code for a DIFFERENT tool (detected by function name mismatch),
        refuses to overwrite to prevent accidental tool destruction.

        On update: creates a .py.bak backup before overwriting and skips the collision
        check (the update action implies intentional overwrite).
        """
        import re as _re

        self._forge_dir.mkdir(parents=True, exist_ok=True)
        source_path = self._forge_dir / f"{name}.py"
        meta_path = self._forge_dir / f"{name}.meta.json"

        is_update = action == "update"

        # ── Backup on update ──
        if is_update and source_path.exists():
            bak_path = self._forge_dir / f"{name}.py.bak"
            bak_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")

        # ── Collision check: prevent overwriting a different tool's file ──
        # Skip on update — the caller intends to overwrite the existing tool.
        if source_path.exists() and not is_update:
            existing_code = source_path.read_text(encoding="utf-8")
            # Extract function names from existing code
            existing_funcs = set(_re.findall(r'^def (\w+)', existing_code, _re.MULTILINE))
            # Extract function names from new code
            new_funcs = set(_re.findall(r'^def (\w+)', code, _re.MULTILINE))

            # If the main function name is different and there's no overlap at all,
            # this is likely a collision — a different tool is being saved to the same name
            if name not in new_funcs and name not in existing_funcs:
                # Neither has a function matching the tool name. Check for any overlap.
                if not existing_funcs.intersection(new_funcs):
                    # No function overlap at all — definitely different tools
                    raise RuntimeError(
                        f"SAFETY: Refusing to overwrite '{source_path}' — existing file "
                        f"contains functions {existing_funcs} which don't match new "
                        f"functions {new_funcs}. This would destroy a different tool. "
                        f"Choose a different tool name."
                    )

        # Save Python source
        source_path.write_text(code, encoding="utf-8")
        # Save metadata (description + parameter schema)
        meta = {
            "name": name,
            "description": description,
            "parameters": parameters or {},
        }
        (self._forge_dir / f"{name}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Update __init__ to ensure package importability
        init_file = self._forge_dir / "__init__.py"
        init_file.touch(exist_ok=True)

    def load_forged_tools(self) -> int:
        """Reload previously forged tools from disk. Returns count loaded.

        Safety: every loaded tool passes through the ToolSandbox before registration.
        Tools that fail the sandbox are skipped and logged to the decision log.

        Parameter schemas are restored from .meta.json files. If no .meta.json
        exists, parameters are auto-inferred from the function signature.
        """
        if not self._forge_dir.exists():
            return 0
        count = 0
        skipped: list[dict] = []
        for pyfile in self._forge_dir.glob("*.py"):
            if pyfile.name == "__init__.py":
                continue
            name = pyfile.stem
            code = pyfile.read_text(encoding="utf-8")

            # ── Sandbox safety check ──
            sandbox_check = self._run_sandbox_check(name, code)
            if not sandbox_check["passed"]:
                skipped.append({
                    "name": name,
                    "report": sandbox_check["report"],
                    "warnings": sandbox_check["warnings"],
                })
                continue  # Skip this tool — it failed the sandbox

            # ── Workspace path validation ──
            path_violations = self._validate_workspace_paths(code)
            if path_violations:
                sandbox_check.setdefault("warnings", []).append({
                    "level": "WARN",
                    "type": "workspace_path_escape",
                    "detail": f"Path violations: {'; '.join(path_violations)}",
                })

            # ── Load metadata ──
            meta_file = self._forge_dir / f"{name}.meta.json"
            description = f"[Forged] {name}"
            parameters = {}
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    description = meta.get("description", description)
                    parameters = meta.get("parameters", {})
                except (json.JSONDecodeError, IOError):
                    pass  # Fall through to auto-inference

            # ── Execute and register ──
            namespace = {}
            try:
                exec(compile(code, str(pyfile), "exec"), namespace)
                candidates = {k: v for k, v in namespace.items() if callable(v) and not k.startswith("_")}
                if candidates:
                    func = candidates.get(name, list(candidates.values())[0])
                    # Auto-infer parameters if no metadata
                    if not parameters:
                        parameters = self._infer_parameters(func)
                    self.registry.register(name, func, description, parameters)
                    self._forged_tools[name] = {
                        "description": description,
                        "code": code,
                        "parameters": parameters,
                    }
                    count += 1
            except Exception:
                skipped.append({
                    "name": name,
                    "report": f"Execution error during load: {traceback.format_exc()}",
                    "warnings": [],
                })

        # ── Log skipped tools ──
        if skipped and self.decision_log:
            for s in skipped:
                self.decision_log.record(
                    context={"action": "load_forged_tool_skipped", "tool_name": s["name"]},
                    decision_type="tool_forge",
                    options_considered=[{"option": "skip", "tool_name": s["name"]}],
                    chosen_option="skip",
                    reasoning=f"Skipped forged tool '{s['name']}' during load: {s['report']}",
                    expected_outcome=f"Tool '{s['name']}' not loaded.",
                    phase="evolve",
                )

        return count

    # ── Management ────────────────────────────────────────────────────

    def list_forged(self) -> dict[str, str]:
        """Return all forged tools and their descriptions."""
        return {name: info["description"] for name, info in self._forged_tools.items()}

    def remove_forged(self, name: str) -> dict:
        """Remove a forged tool from the registry and delete its source + metadata."""
        if name not in self._forged_tools:
            return {"success": False, "error": f"No forged tool named '{name}'."}
        self.registry.remove(name)
        del self._forged_tools[name]
        source_file = self._forge_dir / f"{name}.py"
        if source_file.exists():
            source_file.unlink()
        meta_file = self._forge_dir / f"{name}.meta.json"
        if meta_file.exists():
            meta_file.unlink()
        return {"success": True, "message": f"Forged tool '{name}' removed."}
