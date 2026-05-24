"""
Knowledge Freshness — check how recently knowledge nodes were updated.

Used by the improvement loop's _eval_knowledge_fresh evaluator.
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from tain_agent.core.time_utils import now


def _resolve_store() -> Path:
    root = Path(__file__).resolve().parent.parent.parent.parent
    return root / "agent_workspace" / "knowledge_garden" / "graph.json"


STORE = _resolve_store()
FRESH_WINDOW_DAYS = 7


def check_freshness() -> dict:
    if not STORE.exists():
        return {"fresh_ratio": 0.0, "fresh_count": 0, "stale_count": 0, "total": 0}

    try:
        g = json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"fresh_ratio": 0.0, "fresh_count": 0, "stale_count": 0, "total": 0}

    nodes = g.get("nodes", {})
    if not nodes:
        return {"fresh_ratio": 0.0, "fresh_count": 0, "stale_count": 0, "total": 0}

    cutoff = now().timestamp() - FRESH_WINDOW_DAYS * 86400
    fresh = 0
    stale = 0

    for node in nodes.values():
        try:
            updated = datetime.fromisoformat(node.get("updated_at", ""))
            if updated.timestamp() > cutoff:
                fresh += 1
            else:
                stale += 1
        except (ValueError, TypeError):
            stale += 1

    return {
        "fresh_ratio": round(fresh / len(nodes), 3),
        "fresh_count": fresh,
        "stale_count": stale,
        "total": len(nodes),
        "window_days": FRESH_WINDOW_DAYS,
    }


def main(action: str = "check_freshness", **kwargs) -> dict:
    return check_freshness()
