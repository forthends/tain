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
    # Creative output
    "poem":             "poetry/",
    "song":             "poetry/",
    "story":            "poetry/",
    "poetic_moment":    "poetry/moments/",

    # Knowledge & learning
    "knowledge":        "knowledge/",
    "concept":          "knowledge/concepts/",
    "research":         "knowledge/research/",

    # Introspection
    "journal":          "journal/",
    "reflection":       "journal/",
    "self_portrait":    "journal/",

    # Commitments & goals
    "commitment":       "commitments/",
    "goal":             "goals/",

    # Reports & evolution
    "report":           "reports/",
    "evolution":        "reports/",
    "milestone":        "reports/",

    # Tools & code
    "tool":             "forged_tools/",
    "tool_test":        "tests/",
    "test":             "tests/",

    # General file storage
    "note":             "files/",
    "creative":         "files/",
    "data":             "files/",
    "capture":          "files/",
    "letter":           "files/",
    "general":          "files/",
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

    Args:
        workspace: The agent's workspace root directory.
        content_type: One of the keys in STORAGE_SCHEMA (e.g. "poem", "knowledge").
        filename: The filename to write (e.g. "spring.md").

    Returns:
        Absolute Path resolved within the workspace.
        Falls back to "files/" for unknown content types.
    """
    subdir = STORAGE_SCHEMA.get(content_type, "files/")
    target = (workspace / subdir / filename).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


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
