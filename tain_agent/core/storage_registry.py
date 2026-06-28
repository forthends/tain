"""
Storage Registry — Semantic workspace layout for agent artifacts.

Every piece of content an agent creates has a semantic type.
This registry maps content types to predictable workspace paths,
so agents don't each reinvent their own directory structure.
"""

from pathlib import Path
from typing import Optional

# ── Semantic content type → workspace-relative directory ──────────────
# Agents call resolve_storage_path("poem", "spring.md") → workspace/poetry/spring.md

STORAGE_SCHEMA: dict[str, str] = {
    # Creative output → L4 Expression
    "poem":             "expression/artifacts/poetry/",
    "song":             "expression/artifacts/poetry/",
    "story":            "expression/artifacts/poetry/",
    "poetic_moment":    "expression/artifacts/poetry/moments/",

    # Knowledge & learning → L3 Cognitive
    "knowledge":        "cognitive/knowledge/",
    "concept":          "cognitive/knowledge/concepts/",
    "research":         "cognitive/knowledge/research/",

    # Introspection → L4 Expression
    "journal":          "expression/artifacts/journal/",
    "reflection":       "expression/artifacts/journal/",
    "self_portrait":    "expression/artifacts/journal/",

    # Commitments & goals → L4 Expression
    "commitment":       "expression/artifacts/commitments/",
    "goal":             "expression/goals/",

    # Reports & evolution → L4 Expression
    "report":           "expression/artifacts/reports/",
    "evolution":        "expression/artifacts/reports/",
    "milestone":        "expression/artifacts/reports/",

    # Tools & code → L2 Capability
    "tool":             "capability/tools/",
    "tool_test":        "capability/tests/",
    "test":             "capability/tests/",

    # General file storage → L4 Expression
    "note":             "expression/artifacts/",
    "creative":         "expression/artifacts/",
    "data":             "expression/artifacts/",
    "capture":          "expression/artifacts/",
    "letter":           "expression/artifacts/",
    "general":          "expression/artifacts/",
}

# ── Directories created when a workspace is initialized ──────────────
WORKSPACE_DIRS: list[str] = [
    "poetry/",
    "poetry/moments/",
    "knowledge/",
    "knowledge/concepts/",
    "knowledge/research/",
    "journal/",
    "commitments/",
    "goals/",
    "reports/",
    "forged_tools/",
    "tests/",
    "files/",
    "logs/",
    "logs/conversations/",
    "state/",
]

# Legacy directories that agents may have created — mapped to canonical paths
LEGACY_MERGE_MAP: dict[str, str] = {
    "poems":                    "poetry",
    "poetic_moments":           "poetry/moments",
    "poetry_garden":            "poetry",
    "poetry_journal":           "journal",
    "knowledge_garden":         "knowledge",
    "rag_index":                "knowledge",
}

# Root-level files that should be moved into canonical directories
ROOT_FILE_MERGE_MAP: dict[str, str] = {
    "poetry-self-portrait.md":          "journal/",
    "poetry_moments.json":              "poetry/moments/",
    "evolution_milestones.jsonl":        "reports/",
    "test_liminal_tool.py":             "tests/",
    "test_forged_tool_v2.py":           "tests/",
    "version.json":                     "state/",
}


def resolve_content_path(workspace: Path, content_type: str,
                         filename: str) -> Path:
    """Resolve a semantic content type + filename to a workspace path.

    Does NOT follow symlinks — validates that every path component stays
    within the workspace boundary.

    Args:
        workspace: The agent's workspace root directory.
        content_type: One of the keys in STORAGE_SCHEMA (e.g. "poem", "knowledge").
        filename: The filename to write (e.g. "spring.md").

    Returns:
        Absolute Path within the workspace.
        Falls back to "files/" for unknown content types.

    Raises:
        ValueError: If any path component escapes the workspace or is a symlink.
    """
    # Reject filenames that attempt path traversal
    if ".." in filename.split("/") or filename.startswith("/"):
        raise ValueError(f"Filename '{filename}' attempts path traversal")

    workspace = workspace.resolve(strict=False)
    subdir = STORAGE_SCHEMA.get(content_type, "files/")
    target = workspace / subdir / filename

    # Resolve without following symlinks on the final component
    # Walk each component manually to detect symlinks
    resolved_parts: list[str] = []
    for part in target.parts:
        resolved_parts.append(part)
        partial = Path(*resolved_parts)
        if partial.exists() and partial.is_symlink():
            raise ValueError(
                f"Symlink detected in path: {partial}. "
                f"Symlinks are not allowed in workspace paths for security."
            )

    # Normalize without following symlinks (resolve parent, append basename)
    parent_resolved = target.parent.resolve(strict=False)
    final_path = parent_resolved / target.name

    # Verify the final path is within workspace
    try:
        final_path.relative_to(workspace)
    except ValueError:
        raise ValueError(
            f"Resolved path '{final_path}' escapes workspace '{workspace}'"
        )

    final_path.parent.mkdir(parents=True, exist_ok=True)
    return final_path


def get_schema_description() -> str:
    """Return a human-readable description of the storage schema for agent prompts."""
    lines = ["Available content types and where they are stored:"]
    seen: dict[str, str] = {}
    for ctype, subdir in sorted(STORAGE_SCHEMA.items()):
        if subdir not in seen:
            seen[subdir] = ctype
            lines.append(f"  {ctype:20s} → {subdir}")
        else:
            lines.append(f"  {ctype:20s} → {subdir}  (same as '{seen[subdir]}')")
    return "\n".join(lines)
