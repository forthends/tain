"""
Knowledge Graph — lightweight JSON-backed node/edge store.

Provides structured knowledge storage so the agent's markdown files
translate into measurable graph nodes tracked by evolution_metrics.
"""

import json
from pathlib import Path
from datetime import datetime
from tain_agent.core.time_utils import now


def _resolve_store() -> Path:
    """Resolve the graph store path relative to the project root (not CWD)."""
    root = Path(__file__).resolve().parent.parent.parent.parent
    return root / "agent_workspace" / "knowledge_garden" / "graph.json"


STORE = _resolve_store()


def _load() -> dict:
    if STORE.exists():
        return json.loads(STORE.read_text(encoding="utf-8"))
    return {"nodes": {}, "edges": []}


def _save(g: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(g, ensure_ascii=False, indent=2), encoding="utf-8")


def add_node(slug: str, title: str = "", source_file: str = "",
             tags: list = None, summary: str = "") -> dict:
    g = _load()
    is_new = slug not in g["nodes"]
    g["nodes"][slug] = {
        "title": title or slug,
        "source_file": source_file,
        "tags": tags or [],
        "summary": summary,
        "created_at": g["nodes"][slug]["created_at"] if not is_new else now().isoformat(),
        "updated_at": now().isoformat(),
    }
    _save(g)
    return {"status": "ok", "node": slug, "total_nodes": len(g["nodes"]), "new": is_new}


def add_edge(from_slug: str, to_slug: str, label: str = "") -> dict:
    g = _load()
    edge = {"from": from_slug, "to": to_slug, "label": label}
    if edge not in g["edges"]:
        g["edges"].append(edge)
    _save(g)
    return {"status": "ok", "total_edges": len(g["edges"])}


def get_stats() -> dict:
    g = _load()
    nodes = g.get("nodes", {})
    edges = g.get("edges", [])
    linked = set()
    for e in edges:
        linked.add(e["from"])
        linked.add(e["to"])
    isolated = len(nodes) - len(linked & set(nodes.keys()))
    return {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "isolated_ratio": round(isolated / max(len(nodes), 1), 3),
    }


def sync_from_markdown(garden_dir: str = None) -> dict:
    """Scan markdown files and register any not yet in the graph."""
    if garden_dir is None:
        root = Path(__file__).resolve().parent.parent.parent.parent
        for candidate in ["knowledge_garden", "knowledge"]:
            candidate_path = root / "agent_workspace" / candidate
            if candidate_path.exists():
                garden_dir = str(candidate_path)
                break
        if garden_dir is None:
            return {"status": "ok", "synced": 0, "total_nodes": 0,
                    "message": "No knowledge directory found"}
    g = _load()
    base = Path(garden_dir)
    added = []
    for md_file in sorted(base.rglob("*.md")):
        slug = md_file.stem
        if slug in g["nodes"]:
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            first_line = content.strip().split("\n")[0].lstrip("#").strip()
        except Exception:
            first_line = ""
        g["nodes"][slug] = {
            "title": first_line or slug,
            "source_file": str(md_file),
            "tags": [],
            "summary": first_line,
            "created_at": now().isoformat(),
            "updated_at": now().isoformat(),
        }
        added.append(slug)
    if added:
        _save(g)
    return {"status": "ok", "synced": len(added), "total_nodes": len(g["nodes"]), "added": added}


# ─── Frontmatter support (Phase 3.1) ──────────────────────────────────

def parse_frontmatter(md_path: str) -> dict:
    """Extract YAML frontmatter from a markdown file.

    Returns dict with name, description, tags, created_at, updated_at, etc.
    Returns empty dict if no frontmatter is found.
    """
    from tain_agent.evolution.skill_exporter import _parse_yaml_frontmatter

    path = Path(md_path)
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8")
    return _parse_yaml_frontmatter(content) or {}


def write_frontmatter(md_path: str, metadata: dict) -> dict:
    """Write or update YAML frontmatter on a markdown file.

    If the file already has frontmatter, merge with existing (new keys win).
    If no frontmatter exists, prepend it.

    Returns status dict.
    """
    from tain_agent.evolution.skill_exporter import SkillMetadata

    path = Path(md_path)
    if not path.exists():
        return {"status": "error", "message": f"File not found: {md_path}"}

    content = path.read_text(encoding="utf-8")
    existing = parse_frontmatter(md_path)

    if existing:
        # Merge: new keys override existing
        existing.update(metadata)
        merged = existing
        # Remove body from existing content
        parts = content.split("---", 2)
        body = parts[2] if len(parts) >= 3 else content
    else:
        merged = metadata
        body = content

    yaml_section = SkillMetadata.to_yaml(merged)
    new_content = yaml_section + "\n" + body.strip() + "\n"
    path.write_text(new_content, encoding="utf-8")

    return {"status": "ok", "file": md_path,
            "had_frontmatter": bool(existing),
            "merged_keys": list(merged.keys())}


def sync_from_frontmatter(garden_dir: str = None) -> dict:
    """Scan .md files, extract YAML frontmatter, and sync to graph.json.

    This replaces sync_from_markdown() — it extracts structured metadata
    (name, description, tags, timestamps) from frontmatter instead of
    guessing from the first line of text.

    Returns sync result with added/updated/skipped counts.
    """
    from datetime import datetime as _dt

    if garden_dir is None:
        root = Path(__file__).resolve().parent.parent.parent.parent
        for candidate in ["knowledge_garden", "knowledge"]:
            candidate_path = root / "agent_workspace" / candidate
            if candidate_path.exists():
                garden_dir = str(candidate_path)
                break
        if garden_dir is None:
            return {"status": "ok", "synced": 0, "total_nodes": 0,
                    "message": "No knowledge directory found"}

    g = _load()
    base = Path(garden_dir)
    if not base.exists():
        return {"status": "ok", "synced": 0, "total_nodes": len(g["nodes"]),
                "message": f"Directory not found: {garden_dir}"}

    added = []
    updated = []
    skipped = []

    for md_file in sorted(base.rglob("*.md")):
        slug = md_file.stem
        fm = parse_frontmatter(str(md_file))

        if fm:
            name = fm.get("name", slug)
            title = fm.get("description", name)[:80] or name
            tags = fm.get("tags", [])
            summary = fm.get("description", "")[:500]
            updated_at = fm.get("updated_at", now().isoformat())
        else:
            # Fallback: infer from content
            try:
                content = md_file.read_text(encoding="utf-8")
                first_line = content.strip().split("\n")[0].lstrip("#").strip()
            except Exception:
                first_line = ""
            name = slug
            title = first_line or slug
            tags = []
            summary = first_line
            updated_at = now().isoformat()
            skipped.append(slug)

        if slug in g["nodes"]:
            # Update existing
            node = g["nodes"][slug]
            node["title"] = title
            node["tags"] = list(set(node.get("tags", []) + tags))
            node["summary"] = summary or node.get("summary", "")
            node["updated_at"] = updated_at
            updated.append(slug)
        else:
            g["nodes"][slug] = {
                "title": title,
                "source_file": str(md_file),
                "tags": tags,
                "summary": summary,
                "created_at": now().isoformat(),
                "updated_at": updated_at,
            }
            added.append(slug)

    if added or updated:
        _save(g)

    return {
        "status": "ok",
        "synced": len(added) + len(updated),
        "added": len(added),
        "updated": len(updated),
        "skipped_no_frontmatter": len(skipped),
        "total_nodes": len(g["nodes"]),
        "new_slugs": added,
    }


def discover_knowledge(garden_dir: str = None) -> list[dict]:
    """Progressive discovery: return only frontmatter summaries for all docs.

    Does NOT load document bodies. Returns just enough metadata for the
    agent to know what knowledge is available, so it can decide what to
    load on demand.

    Each entry: {name, description, tags, path, updated_at}
    Typical token cost: ~100 tokens per document.

    Used at agent startup to inject knowledge index into system prompt.
    """
    if garden_dir is None:
        root = Path(__file__).resolve().parent.parent.parent.parent
        candidates = [
            root / "agent_workspace" / "knowledge_garden",
            root / "agent_workspace" / "knowledge",
        ]
        garden_dir = None
        for c in candidates:
            if c.exists():
                garden_dir = str(c)
                break
        if garden_dir is None:
            return []

    base = Path(garden_dir)
    if not base.exists():
        return []

    results = []
    for md_file in sorted(base.rglob("*.md")):
        fm = parse_frontmatter(str(md_file))
        if fm:
            results.append({
                "name": fm.get("name", md_file.stem),
                "description": fm.get("description", "")[:200],
                "tags": fm.get("tags", []),
                "path": str(md_file),
                "updated_at": fm.get("updated_at", ""),
            })
        else:
            # Legacy doc without frontmatter — include basic info
            results.append({
                "name": md_file.stem.lower().replace("_", "-"),
                "description": md_file.stem.replace("_", " ").title(),
                "tags": [],
                "path": str(md_file),
                "updated_at": "",
            })

    return results


def upgrade_legacy_doc(md_path: str) -> dict:
    """Upgrade a single legacy .md file by adding YAML frontmatter.

    Infers: name from filename, description from first heading,
            tags from existing graph.json entry if available.

    Returns status dict.
    """
    path = Path(md_path)
    if not path.exists():
        return {"status": "error", "message": f"File not found: {md_path}"}

    if has_frontmatter(path):
        return {"status": "skipped", "message": f"Already has frontmatter: {md_path}"}

    content = path.read_text(encoding="utf-8")
    lines = content.strip().split("\n")

    name = path.stem.lower().replace("_", "-")
    first_line = ""
    for line in lines:
        s = line.strip()
        if s and not s.startswith("---"):
            first_line = s.lstrip("#").strip()
            break
    description = first_line[:1024] if first_line else path.stem.replace("_", " ").title()

    # Try graph.json for tags
    tags = []
    g = _load()
    node = g["nodes"].get(path.stem)
    if node and node.get("tags"):
        tags = node["tags"]

    fm = {
        "name": name,
        "description": description,
        "tags": tags,
        "updated_at": now().isoformat(),
    }

    return write_frontmatter(md_path, fm)


def has_frontmatter(md_path: Path) -> bool:
    """Check if a .md file already has YAML frontmatter."""
    try:
        return md_path.read_text(encoding="utf-8").startswith("---")
    except Exception:
        return False


SCHEMA = {
    "name": "knowledge_graph",
    "description": (
        "Manage the structured knowledge graph. Supports adding nodes/edges, "
        "syncing from markdown files with YAML frontmatter, and progressive "
        "knowledge discovery (load only metadata, not full content)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Action: add_node, add_edge, get_stats, sync_from_markdown, sync_from_frontmatter, discover_knowledge, upgrade_legacy_doc",
            },
            "slug": {"type": "string", "description": "Node slug for add_node."},
            "title": {"type": "string", "description": "Title for add_node."},
            "source_file": {"type": "string", "description": "Source file path."},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags list."},
            "summary": {"type": "string", "description": "Brief summary."},
            "from_slug": {"type": "string", "description": "Source node for add_edge."},
            "to_slug": {"type": "string", "description": "Target node for add_edge."},
            "label": {"type": "string", "description": "Edge label."},
            "garden_dir": {"type": "string", "description": "Knowledge garden directory path."},
            "md_path": {"type": "string", "description": "Path to .md file for upgrade_legacy_doc."},
        },
    },
}


def main(action: str = "get_stats", **kwargs) -> dict:
    actions = {
        "add_node": lambda: add_node(**kwargs),
        "add_edge": lambda: add_edge(**kwargs),
        "get_stats": get_stats,
        "sync_from_markdown": lambda: sync_from_markdown(**kwargs),
        "sync_from_frontmatter": lambda: sync_from_frontmatter(**kwargs),
        "discover_knowledge": lambda: discover_knowledge(**kwargs),
        "upgrade_legacy_doc": lambda: upgrade_legacy_doc(
            kwargs.get("md_path", "")),
        "parse_frontmatter": lambda: parse_frontmatter(
            kwargs.get("md_path", "")),
        "write_frontmatter": lambda: write_frontmatter(
            kwargs.get("md_path", ""), {k: v for k, v in kwargs.items()
                                         if k not in ("action", "md_path")}),
    }
    fn = actions.get(action)
    if fn:
        return fn()
    return {"status": "error", "message": f"Unknown action: {action}"}
