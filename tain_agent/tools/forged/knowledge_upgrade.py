"""
knowledge_upgrade — batch-upgrade legacy markdown files to SKILL.md format.

Scans the knowledge garden for .md files without YAML frontmatter and
adds structured metadata (name, description, tags) inferred from content.

Delegates to knowledge_graph.py for shared frontmatter operations.

Design: Phase 3.1 §3.5.
"""

import json
from pathlib import Path
from typing import Optional


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


SCHEMA = {
    "name": "knowledge_upgrade",
    "description": (
        "Upgrade legacy knowledge documents to agentskills.io SKILL.md format "
        "by adding YAML frontmatter (name, description, tags) to .md files "
        "that don't already have it. Metadata is inferred from file content "
        "and existing graph.json entries. Safe — never overwrites existing frontmatter."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "garden_dir": {
                "type": "string",
                "description": "Path to the knowledge garden directory. Defaults to agent_workspace/knowledge_garden/.",
            },
            "dry_run": {
                "type": "boolean",
                "description": "If true, only report what would change without making changes.",
            },
        },
    },
}


def main(garden_dir: str = "", dry_run: bool = False) -> dict:
    """Upgrade legacy knowledge .md files with YAML frontmatter.

    Args:
        garden_dir: Path to the knowledge garden. Defaults to workspace or built-in.
        dry_run: Report what would change without making changes.

    Returns:
        dict with upgraded count, skipped count, and per-file details.
    """
    from tain_agent.tools.forged.knowledge_graph import (
        has_frontmatter,
        write_frontmatter,
        _load as load_graph,
        parse_frontmatter,
    )

    root = _project_root()

    # Resolve garden directory
    if garden_dir:
        gd = Path(garden_dir)
    else:
        candidates = [
            root / "agent_workspace" / "knowledge_garden",
            root / "agent_workspace" / "knowledge",
        ]
        gd = None
        for c in candidates:
            if c.exists():
                gd = c
                break
        if gd is None:
            return {
                "upgraded": 0,
                "skipped": 0,
                "error": "No knowledge garden directory found. Set garden_dir manually.",
                "details": [],
            }

    if not gd.exists():
        return {
            "upgraded": 0, "skipped": 0,
            "error": f"Directory not found: {gd}",
            "details": [],
        }

    # Load graph.json for tag inference
    graph_data = None
    graph_path = gd / "graph.json"
    if graph_path.exists():
        try:
            graph_data = load_graph()
        except Exception:
            pass

    md_files = list(gd.rglob("*.md"))
    if not md_files:
        return {
            "upgraded": 0, "skipped": 0,
            "message": "No .md files found in garden directory.",
            "details": [],
        }

    upgraded = 0
    skipped = 0
    details = []

    for md_file in sorted(md_files):
        relative = str(md_file.relative_to(gd))
        if has_frontmatter(md_file):
            skipped += 1
            details.append({
                "file": relative,
                "action": "skipped",
                "reason": "Already has frontmatter",
            })
            continue

        # Try parsing existing frontmatter first, then infer
        fm = parse_frontmatter(str(md_file))
        if not fm:
            # Infer from content
            content = md_file.read_text(encoding="utf-8")
            lines = content.strip().split("\n")
            name = md_file.stem.lower().replace("_", "-")
            first_line = ""
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("---"):
                    first_line = stripped.lstrip("#").strip()
                    break
            description = first_line[:1024] if first_line else f"Knowledge document: {md_file.stem}"

            tags = []
            if graph_data and "nodes" in graph_data:
                node = graph_data["nodes"].get(md_file.stem)
                if node and node.get("tags"):
                    tags = node["tags"]

            fm = {
                "name": name,
                "description": description,
                "tags": tags,
            }

        if not dry_run:
            write_frontmatter(str(md_file), fm)
        upgraded += 1
        details.append({
            "file": relative,
            "action": "would_upgrade" if dry_run else "upgraded",
            "frontmatter": fm,
        })

    return {
        "upgraded": upgraded,
        "skipped": skipped,
        "total": len(md_files),
        "garden_dir": str(gd),
        "dry_run": dry_run,
        "details": details,
        "message": (
            f"{'Would upgrade' if dry_run else 'Upgraded'} {upgraded} file(s), "
            f"skipped {skipped} (already have frontmatter). "
            f"Total: {len(md_files)} .md files in {gd}"
        ),
    }
