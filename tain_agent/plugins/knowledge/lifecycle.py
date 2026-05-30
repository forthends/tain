"""Knowledge lifecycle — conflict detection, freshness checking, inheritance."""

from __future__ import annotations
from datetime import datetime, timezone
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
