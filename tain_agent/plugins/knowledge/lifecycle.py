"""Knowledge lifecycle — conflict detection, freshness checking, inheritance."""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def conflict_detect(
    existing_facts: list[dict[str, Any]],
    new_subject: str,
    new_predicate: str,
    new_object: str,
) -> list[dict[str, Any]]:
    """Detect conflicts between a new fact and existing facts.

    Returns a list of conflicting facts (each dict with subject, predicate, object).
    """
    conflicts: list[dict[str, Any]] = []
    opposites = {
        "is": "is_not", "has": "lacks",
        "supports": "opposes", "believes": "disbelieves",
        "loves": "hates", "knows": "is_ignorant_of",
    }
    inverted = {v: k for k, v in opposites.items()}
    merged = {**opposites, **inverted}

    for fact in existing_facts:
        s = fact.get("subject", "")
        p = fact.get("predicate", "")
        o = fact.get("object", "")

        # Same subject + predicate, different object → conflict
        if s == new_subject and p == new_predicate and o != new_object:
            conflicts.append(fact)
        # Opposite predicates between same pair
        if (
            (s == new_subject and o == new_object and merged.get(p) == new_predicate)
            or (s == new_object and o == new_subject and merged.get(p) == new_predicate)
        ):
            conflicts.append(fact)

    return conflicts


def freshness_check(
    created_at: str,
    max_age_days: float = 30.0,
    now: str | None = None,
) -> tuple[bool, float]:
    """Check whether a knowledge item is still fresh.

    Returns (is_fresh, age_days).
    """
    if now is None:
        now = datetime.now(timezone.utc).isoformat()

    try:
        created_dt = datetime.fromisoformat(created_at)
        now_dt = datetime.fromisoformat(now)
    except (ValueError, TypeError):
        return False, float("inf")

    age_seconds = (now_dt - created_dt).total_seconds()
    age_days = age_seconds / 86400.0
    return age_days <= max_age_days, age_days


def inherit_entities(
    source_graph: dict[str, Any],
    target_graph: dict[str, Any],
    entity_ids: list[str],
) -> dict[str, Any]:
    """Inherit specified entities + their relations from source into target graph.

    Returns the updated target graph dict.
    """
    target = dict(target_graph)
    if "entities" not in target:
        target["entities"] = {}
    if "relations" not in target:
        target["relations"] = []

    source_entities = source_graph.get("entities", {})
    source_relations = source_graph.get("relations", [])

    for eid in entity_ids:
        if eid in source_entities:
            target["entities"][eid] = dict(source_entities[eid])

    # Copy relations where both source and target are in the relevant set
    relevant = set(entity_ids) | set(target["entities"].keys())
    for rel in source_relations:
        if rel["source"] in relevant or rel["target"] in relevant:
            # Avoid duplicates
            already_exists = any(
                r["source"] == rel["source"]
                and r["relation"] == rel["relation"]
                and r["target"] == rel["target"]
                for r in target["relations"]
            )
            if not already_exists:
                target["relations"].append(dict(rel))

    return target


def _project_root() -> Path:
    """Return the project root directory (four levels up from lifecycle.py)."""
    return Path(__file__).resolve().parent.parent.parent.parent


def _references_file(agent_name: str) -> Path:
    """Return the path to an agent's references.jsonl file."""
    return _project_root() / "agent_workspace" / agent_name / "knowledge" / "references.jsonl"


def add_reference(
    source_agent: str, path: str, category: str, target_agent: str
) -> dict:
    """Create a read-only reference to another agent's knowledge document.

    Validation: checks that the source file exists at
    agent_workspace/{source_agent}/knowledge/{path} before accepting.

    Returns:
        {"success": True, "reference_id": "agent::path", "record": {...}}
        or {"success": False, "error": "..."}
    """
    root = _project_root()
    source_file = root / "agent_workspace" / source_agent / "knowledge" / path

    if not source_file.exists():
        return {"success": False, "error": f"Source file not found: {source_file}"}

    reference_id = f"{source_agent}::{path}"
    now = datetime.now(timezone.utc).isoformat()

    record: dict[str, Any] = {
        "reference_id": reference_id,
        "source_agent": source_agent,
        "path": path,
        "category": category,
        "imported_at": now,
        "last_synced": now,
        "status": "active",
    }

    ref_file = _references_file(target_agent)
    ref_file.parent.mkdir(parents=True, exist_ok=True)

    # Check for duplicates
    existing = list_references(target_agent)
    for ref in existing.get("references", []):
        if ref.get("reference_id") == reference_id:
            return {
                "success": False,
                "error": f"Reference already exists: {reference_id}",
            }

    with open(ref_file, "a") as f:
        f.write(json.dumps(record) + "\n")

    return {"success": True, "reference_id": reference_id, "record": record}


def list_references(agent_name: str) -> dict:
    """List all active knowledge references from the agent's references.jsonl file.

    Returns:
        {"success": True, "references": [...], "count": N}
    """
    ref_file = _references_file(agent_name)

    if not ref_file.exists():
        return {"success": True, "references": [], "count": 0}

    references: list[dict[str, Any]] = []
    with open(ref_file, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    references.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return {"success": True, "references": references, "count": len(references)}


def sync_references(agent_name: str) -> dict:
    """Re-read all referenced files, update last_synced timestamp.

    Marks references as "broken" if the source file no longer exists.

    Returns:
        {"success": True, "synced": N, "message": "..."}
    """
    result = list_references(agent_name)
    references = result.get("references", [])

    if not references:
        return {"success": True, "synced": 0, "message": "No references to sync"}

    root = _project_root()
    now = datetime.now(timezone.utc).isoformat()
    synced = 0

    for ref in references:
        if ref.get("status") == "broken":
            continue
        source_file = (
            root / "agent_workspace" / ref["source_agent"] / "knowledge" / ref["path"]
        )
        if source_file.exists():
            ref["last_synced"] = now
            synced += 1
        else:
            ref["status"] = "broken"

    # Rewrite the file with updated records
    ref_file = _references_file(agent_name)
    ref_file.parent.mkdir(parents=True, exist_ok=True)
    with open(ref_file, "w") as f:
        for ref in references:
            f.write(json.dumps(ref) + "\n")

    return {"success": True, "synced": synced, "message": f"Synced {synced} references"}


def get_referenced_files(agent_name: str) -> list[Path]:
    """Get a list of absolute Path objects to all actively referenced knowledge files.

    Used by quality gate S2 to count referenced documents.
    Returns empty list if no references file exists.
    """
    result = list_references(agent_name)
    references = result.get("references", [])

    root = _project_root()
    files: list[Path] = []
    for ref in references:
        if ref.get("status") != "broken":
            source_file = (
                root
                / "agent_workspace"
                / ref["source_agent"]
                / "knowledge"
                / ref["path"]
            )
            files.append(source_file)

    return files
