"""
Knowledge Subgraph — check structural balance of the knowledge graph.

Used by the improvement loop's _eval_subgraph_balance evaluator.
"""

import json
from pathlib import Path


def _resolve_store() -> Path:
    root = Path(__file__).resolve().parent.parent.parent.parent
    return root / "agent_workspace" / "knowledge_garden" / "graph.json"


STORE = _resolve_store()


def check_balance() -> dict:
    if not STORE.exists():
        return {"balance_score": 1.0, "total_nodes": 0, "isolated_nodes": 0,
                "connected_nodes": 0, "summary": "No knowledge graph data."}

    try:
        g = json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"balance_score": 1.0, "total_nodes": 0, "isolated_nodes": 0,
                "connected_nodes": 0, "summary": "Failed to read graph data."}

    nodes = g.get("nodes", {})
    edges = g.get("edges", [])

    if not nodes:
        return {"balance_score": 1.0, "total_nodes": 0, "isolated_nodes": 0,
                "connected_nodes": 0, "summary": "No knowledge nodes yet."}

    linked = set()
    for e in edges:
        linked.add(e.get("from", ""))
        linked.add(e.get("to", ""))

    all_slugs = set(nodes.keys())
    connected = linked & all_slugs
    isolated = all_slugs - connected

    balance_score = len(connected) / len(nodes) if nodes else 1.0

    return {
        "balance_score": round(balance_score, 3),
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "connected_nodes": len(connected),
        "isolated_nodes": len(isolated),
        "isolated_slugs": sorted(isolated),
        "summary": f"Balance: {balance_score:.2f} | {len(connected)} connected, "
                   f"{len(isolated)} isolated out of {len(nodes)} nodes",
    }


def main(action: str = "check_balance", **kwargs) -> dict:
    return check_balance()
