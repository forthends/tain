"""
export_as_skill — export forged tools as agentskills.io standard Skills.

Converts a Tain Agent forged tool (Python .py + .meta.json) into a
standard Agent Skill directory (SKILL.md + scripts/ + references/)
that can be consumed by Claude Code, Copilot, Cursor, and other agents.

Design: Phase 3.1 §2.5.
"""

import json
from pathlib import Path

SCHEMA = {
    "name": "export_as_skill",
    "description": (
        "Export a forged tool as a standard Agent Skill (agentskills.io format). "
        "Creates a SKILL.md with YAML frontmatter + scripts/main.py + references/schema.json. "
        "The exported skill can be used by Claude Code, Copilot, Cursor, and other "
        "agents that support the Agent Skills specification. "
        "Use this when you want your tools to be portable and reusable by other agents."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "Name of the forged tool to export as a Skill (e.g. 'regression_tester').",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory to write the Skill package (default: 'skills').",
            },
            "validate": {
                "type": "boolean",
                "description": "Whether to run validation after export (default: true).",
            },
        },
        "required": ["tool_name"],
    },
}


def main(tool_name: str, output_dir: str = "skills", validate: bool = True) -> dict:
    """Export a forged tool as a standard Agent Skill.

    Args:
        tool_name: Name of the forged tool to export.
        output_dir: Directory for the Skill output.
        validate: Run agentskills.io spec validation after export.

    Returns:
        dict with export result, validation status, and Skill path.
    """
    from tain_agent.evolution.skill_exporter import SkillExporter, validate_skill

    # Try to load agent identity for metadata
    agent_name = ""
    agent_version = ""
    evolution_cycles = 0

    ws = Path("agent_workspace")
    if ws.exists():
        state_dir = ws / "state"
        version_path = state_dir / "version.json"
        if version_path.exists():
            try:
                vdata = json.loads(version_path.read_text(encoding="utf-8"))
                agent_version = vdata.get("version", "")
            except (json.JSONDecodeError, IOError):
                pass

        personality_path = state_dir / "personality.json"
        if personality_path.exists():
            try:
                pdata = json.loads(personality_path.read_text(encoding="utf-8"))
                agent_name = pdata.get("name", pdata.get("agent_name", ""))
            except (json.JSONDecodeError, IOError):
                pass

    exporter = SkillExporter(
        agent_name=agent_name,
        agent_version=agent_version,
        evolution_cycles=evolution_cycles,
    )

    skill_path = exporter.export_tool_as_skill(tool_name, output_dir=output_dir)

    if skill_path is None:
        # Try listing available tools from all sources
        available = []
        for candidate in [
            Path("agent_workspace/forged_tools"),
            Path("tain_agent/tools/forged"),
        ]:
            if candidate.exists():
                for f in candidate.glob("*.py"):
                    if not f.name.startswith("_") and f.name != "smart_improve.py" and f.stem not in available:
                        available.append(f.stem)
        available = sorted(available)
        return {
            "exported": False,
            "error": f"Tool '{tool_name}' not found.",
            "available_tools": available,
            "hint": "Use one of the available tools listed above.",
        }

    result = {
        "exported": True,
        "skill_name": skill_path.name,
        "skill_path": str(skill_path),
        "files": [str(f.relative_to(skill_path))
                  for f in sorted(skill_path.rglob("*")) if f.is_file()],
    }

    if validate:
        validation = validate_skill(str(skill_path))
        result["validation"] = validation
        if not validation["valid"]:
            result["warning"] = (
                "Skill was created but has validation errors. "
                "See validation.errors for details."
            )
        if validation.get("warnings"):
            result["warnings"] = validation["warnings"]

    result["message"] = (
        f"Successfully exported '{tool_name}' as Agent Skill '{skill_path.name}'. "
        f"To use with Claude Code, copy to ~/.claude/skills/{skill_path.name}/ "
        f"or .claude/skills/{skill_path.name}/ in your project."
    )
    return result


if __name__ == "__main__":
    import sys
    tool = sys.argv[1] if len(sys.argv) > 1 else "regression_tester"
    result = main(tool_name=tool)
    print(json.dumps(result, indent=2, ensure_ascii=False))
