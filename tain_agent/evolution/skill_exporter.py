"""
Skill Exporter — convert forged tools to agentskills.io standard format.

Transforms Tain Agent forged tools (Python .py + .meta.json) into
standard Agent Skills (SKILL.md + scripts/ + references/) that can
be consumed by Claude Code, Copilot, Cursor, and other agents.

Design: Phase 3.1 §2.
"""

import ast
import json
import re
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


# ─── SKILL.md template ─────────────────────────────────────────────────

_SKILL_BODY_TEMPLATE = """# {title}

## What this tool does

{description}

## Parameters

{parameters_doc}

## Returns

{returns_doc}

## Usage Example

{usage_example}

## Script

Run with: `python scripts/main.py`
"""


# ─── SkillMetadata ─────────────────────────────────────────────────────

class SkillMetadata:
    """Generates YAML frontmatter from forged tool metadata."""

    @staticmethod
    def from_tool_meta(meta_json: dict, py_code: str = "",
                       agent_name: str = "", agent_version: str = "",
                       evolution_cycles: int = 0) -> dict:
        """Build YAML frontmatter dict from a .meta.json file.

        Args:
            meta_json: Parsed .meta.json content.
            py_code: Tool source code (for import inference).
            agent_name: Name of the forging agent.
            agent_version: Version when forged.
            evolution_cycles: Evolution count when forged.
        """
        name = meta_json.get("name", "unknown-tool")
        # Convert to agentskills.io naming: lowercase, hyphens only
        skill_name = name.lower().replace("_", "-")

        description = meta_json.get("description", f"Tool: {name}")
        # Truncate to spec limit
        if len(description) > 1024:
            description = description[:1021] + "..."

        params = meta_json.get("parameters", {})

        # Gather metadata
        md = {
            "tao_tool_id": name,
        }
        if agent_name:
            md["forged_by"] = agent_name
        if agent_version:
            md["agent_version"] = agent_version
        if evolution_cycles:
            md["evolution_cycles"] = evolution_cycles
        if params:
            md["parameters"] = params

        return {
            "name": skill_name,
            "description": description,
            "compatibility": "requires Python 3.9+, tain_agent runtime",
            "metadata": md,
        }

    @staticmethod
    def from_knowledge_doc(md_path: str) -> dict:
        """Extract frontmatter from a knowledge .md file.

        Returns existing frontmatter if present, otherwise infers from content.
        """
        path = Path(md_path)
        content = path.read_text(encoding="utf-8")

        existing = _parse_yaml_frontmatter(content)
        if existing:
            return existing

        # Infer from content
        name = path.stem.lower().replace("_", "-")
        lines = content.strip().split("\n")
        first_line = lines[0].lstrip("#").strip() if lines else ""
        description = first_line[:1024] if first_line else f"Knowledge: {path.stem}"

        return {
            "name": name,
            "description": description,
            "tags": [],
            "metadata": {
                "source_file": str(path),
                "updated_at": _now_iso(),
            },
        }

    @staticmethod
    def to_yaml(frontmatter: dict) -> str:
        """Serialize a frontmatter dict to YAML string."""
        lines = ["---"]
        # Top-level fields (ordered: name, description, license, compatibility,
        # allowed-tools, tags, metadata)
        top_fields = ["name", "description", "license", "compatibility",
                      "allowed-tools", "tags", "model", "canonical_url"]

        for key in top_fields:
            if key in frontmatter:
                lines.append(_yaml_line(key, frontmatter[key]))

        # Any remaining top-level keys not in the ordered list (except metadata)
        for key in frontmatter:
            if key not in top_fields and key != "metadata":
                lines.append(_yaml_line(key, frontmatter[key]))

        # Metadata block
        if "metadata" in frontmatter and frontmatter["metadata"]:
            lines.append("metadata:")
            for mk, mv in frontmatter["metadata"].items():
                lines.append(_yaml_nested(mk, mv))

        lines.append("---")
        return "\n".join(lines) + "\n"


def _yaml_line(key: str, value) -> str:
    """Format a key: value YAML line."""
    if isinstance(value, str):
        # Escape special chars
        if any(c in value for c in [":", "#", "{", "}", "[", "]", ",", "&", "*", "?", "|", "-", "<", ">", "=", "!", "%", "@", "`"]):
            return f'{key}: "{value}"'
        return f"{key}: {value}"
    elif isinstance(value, bool):
        return f"{key}: {'true' if value else 'false'}"
    elif isinstance(value, (int, float)):
        return f"{key}: {value}"
    elif isinstance(value, list):
        if not value:
            return f"{key}: []"
        items = []
        for v in value:
            if isinstance(v, str):
                items.append(f"  - {v}")
            else:
                items.append(f"  - {json.dumps(v)}")
        return f"{key}:\n" + "\n".join(items)
    elif isinstance(value, dict):
        if not value:
            return f"{key}: {{}}"
        return f"{key}: {json.dumps(value)}"
    return f'{key}: "{str(value)}"'


def _yaml_nested(key: str, value, indent: int = 2) -> str:
    """Format a nested YAML value."""
    prefix = " " * indent
    if isinstance(value, str):
        return f'{prefix}{key}: "{value}"'
    elif isinstance(value, bool):
        return f"{prefix}{key}: {'true' if value else 'false'}"
    elif isinstance(value, (int, float)):
        return f"{prefix}{key}: {value}"
    elif isinstance(value, dict):
        lines = [f"{prefix}{key}:"]
        for k, v in value.items():
            if isinstance(v, (str, bool, int, float)):
                lines.append(f"  {prefix}{k}: {_yaml_scalar(v)}")
            else:
                lines.append(f"  {prefix}{k}: {json.dumps(v)}")
        return "\n".join(lines)
    elif isinstance(value, list):
        if not value:
            return f"{prefix}{key}: []"
        items = [f"{prefix}  - {_yaml_scalar(v)}" for v in value]
        return f"{prefix}{key}:\n" + "\n".join(items)
    return f"{prefix}{key}: {str(value)}"


def _yaml_scalar(v) -> str:
    if isinstance(v, str):
        return f'"{v}"' if any(c in v for c in ':#{}[],&*?!|-<>=!%@`') else v
    elif isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


# ─── SkillBodyGenerator ────────────────────────────────────────────────

class SkillBodyGenerator:
    """Generates SKILL.md body content from Python code or markdown docs."""

    @staticmethod
    def from_python_code(code: str, parameters: dict = None,
                         description: str = "") -> str:
        """Analyze Python code via AST and generate usage documentation.

        Extracts: function signatures, docstrings, parameter info.
        """
        title = "Tool Usage"
        params_doc = "_No parameters documented._"
        returns_doc = "_Not documented._"
        usage_example = "_See `scripts/main.py` for implementation._"

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return _SKILL_BODY_TEMPLATE.format(
                title=title, description=description,
                parameters_doc=params_doc, returns_doc=returns_doc,
                usage_example=usage_example,
            )

        # Find the main callable function
        funcs = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    funcs.append(node)

        if not funcs:
            return _SKILL_BODY_TEMPLATE.format(
                title=title, description=description,
                parameters_doc=params_doc, returns_doc=returns_doc,
                usage_example=usage_example,
            )

        # Prefer 'main', otherwise largest function
        main_func = None
        for f in funcs:
            if f.name == "main":
                main_func = f
                break
        if main_func is None:
            main_func = max(funcs, key=lambda f: len(f.args.args))

        title = main_func.name.replace("_", " ").title()

        # Extract docstring
        docstring = ast.get_docstring(main_func)
        if docstring:
            description = docstring

        # Build parameter documentation
        param_lines = []
        if parameters:
            for pname, pmeta in parameters.items():
                if isinstance(pmeta, dict):
                    ptype = pmeta.get("type", "string")
                    pdesc = pmeta.get("description", "")
                    preq = "required" if pmeta.get("required", True) else "optional"
                    param_lines.append(
                        f"- `{pname}` ({ptype}, {preq}): {pdesc}"
                    )
                else:
                    param_lines.append(f"- `{pname}`: {pmeta}")
        else:
            # Infer from function signature
            for arg in main_func.args.args:
                argname = arg.arg
                if argname in ("self", "cls"):
                    continue
                argtype = "string"
                if arg.annotation:
                    argtype = _annotation_name(arg.annotation)
                param_lines.append(f"- `{argname}` ({argtype}): Parameter description needed.")

        if param_lines:
            params_doc = "\n".join(param_lines)

        # Return type inference
        returns = main_func.returns
        if returns:
            returns_doc = f"Returns `{_annotation_name(returns)}`. See script for details."

        # Build usage example
        func_name = main_func.name
        arg_names = [a.arg for a in main_func.args.args if a.arg not in ("self", "cls")]
        arg_str = ", ".join(f"{a}=..." for a in arg_names)
        usage_example = (
            f"```python\n"
            f"from scripts.main import {func_name}\n\n"
            f"result = {func_name}({arg_str})\n"
            f"```"
        )

        return _SKILL_BODY_TEMPLATE.format(
            title=title,
            description=description,
            parameters_doc=params_doc,
            returns_doc=returns_doc,
            usage_example=usage_example,
        )

    @staticmethod
    def from_knowledge_doc(md_content: str) -> str:
        """Extract body from a markdown document, stripping YAML frontmatter."""
        if md_content.startswith("---"):
            parts = md_content.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return md_content.strip()


def _annotation_name(node) -> str:
    """Get a JSON-Schema-compatible type name from an AST annotation node."""
    _PY_TO_JSON = {"int": "integer", "float": "number", "bool": "boolean",
                   "str": "string", "list": "array", "dict": "object"}
    if isinstance(node, ast.Name):
        return _PY_TO_JSON.get(node.id, node.id)
    elif isinstance(node, ast.Constant):
        return str(node.value)
    elif isinstance(node, ast.Subscript):
        value = _annotation_name(node.value)
        return f"{value}[...]"
    return "any"


# ─── YAML frontmatter parser (no pyyaml dependency) ────────────────────

def _parse_yaml_frontmatter(text: str) -> Optional[dict]:
    """Parse YAML frontmatter from text. Returns None if absent.

    Uses pyyaml if available (per design §7), falls back to a simple
    built-in parser for environments without pyyaml.
    """
    if not text.startswith("---"):
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    yaml_str = parts[1].strip()
    if not yaml_str:
        return None

    # Prefer pyyaml per design spec
    try:
        import yaml
        result = yaml.safe_load(yaml_str)
        if isinstance(result, dict):
            return result
        return {}
    except (ImportError, Exception):
        pass

    return _parse_simple_yaml(yaml_str)


def _parse_simple_yaml(text: str) -> dict:
    """Parse a simple YAML subset into a dict."""
    result = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        # Skip empty lines and comments
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue

        # Check indentation level
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if indent == 0:
            # Top-level key
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip()
                if val:
                    result[key] = _yaml_value(val)
                    i += 1
                else:
                    # Check if next line is indented (nested object)
                    if i + 1 < len(lines) and lines[i + 1].startswith("  "):
                        nested_lines = []
                        i += 1
                        while i < len(lines) and (lines[i].startswith("  ") or not lines[i].strip()):
                            if lines[i].strip():
                                nested_lines.append(lines[i])
                            i += 1
                        nested_text = "\n".join(nested_lines)
                        # Check if list items
                        if nested_lines and nested_lines[0].strip().startswith("- "):
                            result[key] = _yaml_list(nested_text)
                        else:
                            result[key] = _parse_simple_yaml(nested_text)
                    else:
                        result[key] = None
                        i += 1
            else:
                i += 1
        else:
            i += 1

    return result


def _yaml_value(val: str):
    """Parse a scalar YAML value."""
    val = val.strip().strip('"').strip("'")
    if val.lower() == "true":
        return True
    elif val.lower() == "false":
        return False
    elif val.lower() == "null" or val.lower() == "~":
        return None
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def _yaml_list(text: str) -> list:
    """Parse a simple YAML list from indented text."""
    items = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(_yaml_value(stripped[2:]))
        elif stripped.startswith("-"):
            items.append(_yaml_value(stripped[1:]))
    return items


# ─── SkillExporter ─────────────────────────────────────────────────────

class SkillExporter:
    """Export forged tools to agentskills.io standard Skill format.

    Usage:
        exporter = SkillExporter(agent_name="Explorer", agent_version="0.23.0")
        skill_path = exporter.export_tool_as_skill("regression_tester")
        # → skills/regression-tester/SKILL.md + scripts/main.py + references/schema.json

        results = exporter.export_all_tools()
        # → list of Paths to created Skill directories
    """

    def __init__(self, agent_name: str = "", agent_version: str = "",
                 evolution_cycles: int = 0):
        self.agent_name = agent_name
        self.agent_version = agent_version
        self.evolution_cycles = evolution_cycles

    def _find_tool_meta(self, tool_name: str) -> Optional[dict]:
        """Find a tool's .meta.json file in both workspace and built-in dirs."""
        search_dirs = [
            _project_root() / "agent_workspace" / "forged_tools",
            _project_root() / "tain_agent" / "tools" / "forged",
        ]
        for d in search_dirs:
            meta_path = d / f"{tool_name}.meta.json"
            if meta_path.exists():
                try:
                    return json.loads(meta_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, IOError):
                    pass
        return None

    def _find_tool_code(self, tool_name: str) -> Optional[str]:
        """Find a tool's .py source code."""
        search_dirs = [
            _project_root() / "agent_workspace" / "forged_tools",
            _project_root() / "tain_agent" / "tools" / "forged",
        ]
        for d in search_dirs:
            py_path = d / f"{tool_name}.py"
            if py_path.exists():
                return py_path.read_text(encoding="utf-8")
        return None

    def _find_tool_file_path(self, tool_name: str) -> Optional[Path]:
        """Find a tool's .py file path."""
        search_dirs = [
            _project_root() / "agent_workspace" / "forged_tools",
            _project_root() / "tain_agent" / "tools" / "forged",
        ]
        for d in search_dirs:
            py_path = d / f"{tool_name}.py"
            if py_path.exists():
                return py_path
        return None

    def export_tool_as_skill(self, tool_name: str,
                             output_dir: str = "skills") -> Optional[Path]:
        """Export a single forged tool as an Agent Skill directory.

        Returns the Path to the created Skill directory, or None if tool not found.
        """
        meta = self._find_tool_meta(tool_name)
        code = self._find_tool_code(tool_name)

        if meta is None and code is None:
            return None

        # Build metadata from available sources
        meta = meta or {"name": tool_name, "description": f"Tool: {tool_name}"}
        if code is None:
            code = "# Source not available\n"

        params = meta.get("parameters", {})

        # Generate frontmatter
        fm = SkillMetadata.from_tool_meta(
            meta, code,
            agent_name=self.agent_name,
            agent_version=self.agent_version,
            evolution_cycles=self.evolution_cycles,
        )

        skill_name = fm["name"]
        skill_dir = Path(output_dir) / skill_name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        skill_dir.mkdir(parents=True)

        # Generate body
        body = SkillBodyGenerator.from_python_code(
            code, params, meta.get("description", ""))

        # Write SKILL.md
        yaml_section = SkillMetadata.to_yaml(fm)
        (skill_dir / "SKILL.md").write_text(
            yaml_section + "\n" + body, encoding="utf-8")

        # Write scripts/main.py
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "main.py").write_text(code, encoding="utf-8")

        # Write references/schema.json
        refs_dir = skill_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "schema.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return skill_dir

    def export_all_tools(self, output_dir: str = "skills") -> list[Path]:
        """Export all forged tools as Agent Skills.

        Returns list of created Skill directory paths.
        """
        results = []
        seen = set()

        search_dirs = [
            _project_root() / "agent_workspace" / "forged_tools",
            _project_root() / "tain_agent" / "tools" / "forged",
        ]

        for d in search_dirs:
            if not d.exists():
                continue
            for py_file in sorted(d.glob("*.py")):
                if py_file.name.startswith("_") or py_file.name == "smart_improve.py":
                    continue
                name = py_file.stem
                if name in seen:
                    continue
                seen.add(name)
                result = self.export_tool_as_skill(name, output_dir)
                if result:
                    results.append(result)

        return results

    def export_knowledge_doc(self, md_path: str,
                              output_dir: str = "skills") -> Optional[Path]:
        """Export a knowledge .md document as a Skill (SKILL.md wrapper).

        If the document already has YAML frontmatter, it's used directly.
        Otherwise, frontmatter is inferred from content.
        """
        path = Path(md_path)
        if not path.exists():
            return None

        content = path.read_text(encoding="utf-8")
        fm = SkillMetadata.from_knowledge_doc(str(path))
        body = SkillBodyGenerator.from_knowledge_doc(content)

        skill_name = fm.get("name", path.stem.lower().replace("_", "-"))
        skill_dir = Path(output_dir) / skill_name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        skill_dir.mkdir(parents=True)

        (skill_dir / "SKILL.md").write_text(
            SkillMetadata.to_yaml(fm) + "\n" + body, encoding="utf-8")

        return skill_dir

    def export_knowledge_as_skills(self, knowledge_dir: str,
                                    output_dir: str = "skills") -> list[Path]:
        """Export all markdown documents in a knowledge directory as Skills.

        Returns list of created Skill directory paths.
        """
        results = []
        kd = Path(knowledge_dir)
        if not kd.exists():
            return results

        for md_file in sorted(kd.rglob("*.md")):
            # Skip SKILL.md files that are already in skill format
            if md_file.name == "SKILL.md":
                continue
            result = self.export_knowledge_doc(str(md_file), output_dir)
            if result:
                results.append(result)

        return results


# ─── Validation ────────────────────────────────────────────────────────

def validate_skill(skill_dir: str) -> dict:
    """Validate a Skill directory against the agentskills.io specification.

    Checks:
      - SKILL.md exists and is valid
      - name matches directory name
      - name conforms to naming rules
      - description is within length limits
      - Directory structure is clean (no unexpected nesting)
    """
    path = Path(skill_dir)
    if not path.is_dir():
        return {"valid": False, "errors": [f"Not a directory: {skill_dir}"]}

    errors = []
    warnings = []

    # Check SKILL.md exists
    skill_md = path / "SKILL.md"
    if not skill_md.exists():
        errors.append("SKILL.md not found")
        return {"valid": False, "errors": errors}

    content = skill_md.read_text(encoding="utf-8")
    fm = _parse_yaml_frontmatter(content)

    if fm is None:
        errors.append("No YAML frontmatter found in SKILL.md")
        return {"valid": False, "errors": errors}

    # Validate name
    name = fm.get("name", "")
    if not name:
        errors.append("Missing 'name' in frontmatter")
    else:
        if not (1 <= len(name) <= 64):
            errors.append(f"Name '{name}' length must be 1-64, got {len(name)}")
        if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$', name):
            errors.append(f"Name '{name}' violates naming rules (lowercase alphanumeric + hyphens)")
        if name != path.name:
            errors.append(f"Name '{name}' does not match directory name '{path.name}'")

    # Validate description
    desc = fm.get("description", "")
    if not desc:
        errors.append("Missing 'description' in frontmatter")
    elif len(desc) > 1024:
        warnings.append(f"Description is {len(desc)} chars (max 1024)")

    # Validate allowed-tools format (if present)
    allowed = fm.get("allowed-tools", "")
    if allowed and not isinstance(allowed, str):
        errors.append("'allowed-tools' must be a space-delimited string")

    # Check body after frontmatter
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) < 3 or not parts[2].strip():
            warnings.append("SKILL.md body is empty — consider adding usage instructions")

    # Check directory structure
    for subdir in path.iterdir():
        if subdir.is_dir():
            if subdir.name not in ("scripts", "references", "assets"):
                warnings.append(f"Unexpected directory: {subdir.name}")

    valid = len(errors) == 0
    return {
        "valid": valid,
        "errors": errors,
        "warnings": warnings,
        "name": name,
        "description_length": len(desc),
        "skill_dir": str(path),
    }
