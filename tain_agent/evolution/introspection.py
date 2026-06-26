"""Lightweight agent introspection API — cheaper than Agent-built tool chains."""
import json as _json
from collections import Counter
from datetime import datetime, timezone, timedelta


def get_self_profile(decision_log, personality, goals, tools_registry,
                     since_days: int = 7) -> str:
    """Return a structured self-profile for the agent.

    Aggregates data from framework-internal sources (decision_log,
    personality, goals, tools) without requiring the agent to scan
    conversation logs or milestones.
    """
    profile = {
        "action_distribution": _action_distribution(decision_log, since_days),
        "tool_usage": _tool_usage_ranking(decision_log, since_days),
        "trait_activity": _trait_activity(personality),
        "active_goals": _active_goals(goals),
        "tool_count": len(tools_registry.list_names()) if tools_registry else 0,
    }
    return _json.dumps(profile, ensure_ascii=False, indent=2)


def _action_distribution(decision_log, since_days: int) -> dict:
    if not decision_log:
        return {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    actions = Counter()
    try:
        for entry in decision_log.read_all():
            ts = entry.get("timestamp", "")
            if ts < cutoff.isoformat():
                continue
            action = entry.get("context", {}).get("action", "unknown")
            actions[action] += 1
    except (AttributeError, TypeError):
        pass
    return dict(actions.most_common(20))


def _tool_usage_ranking(decision_log, since_days: int) -> list:
    if not decision_log:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    tools = Counter()
    try:
        for entry in decision_log.read_all():
            ts = entry.get("timestamp", "")
            if ts < cutoff.isoformat():
                continue
            tool = entry.get("context", {}).get("tool_name", "")
            if tool:
                tools[tool] += 1
    except (AttributeError, TypeError):
        pass
    return [{"tool": t, "calls": c} for t, c in tools.most_common(15)]


def _trait_activity(personality) -> dict:
    if not personality:
        return {}
    result = {}
    try:
        traits = personality._traits
    except AttributeError:
        return {}
    for cat, trait_list in traits.items():
        if trait_list:
            result[cat] = [
                {"value": t.get("value", ""), "confidence": t.get("confidence", 0)}
                for t in trait_list
            ]
    return result


def _active_goals(goals) -> list:
    if not goals:
        return []
    active = []
    for g in getattr(goals, '_goals', {}).values():
        if getattr(g, 'status', '') in ("in_progress", "pending", "blocked"):
            active.append({"id": g.id, "description": g.description})
    return active
