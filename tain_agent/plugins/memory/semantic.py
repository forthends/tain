"""Semantic memory — JSON-backed knowledge graph for entities and relations."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any


class SemanticStore:
    """In-memory knowledge graph persisted as JSON.

    Nodes represent entities (concepts, people, tools, etc.).
    Edges represent typed relationships between entities.
    """

    def __init__(self, store_path: Path | str | None = None):
        self._store_path = Path(store_path) if store_path else None
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: list[dict[str, Any]] = []

    def initialize(self) -> None:
        if self._store_path:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            self._load()

    def shutdown(self) -> None:
        if self._store_path:
            self.save()

    def health_check(self) -> str:
        return "ok"

    # ── Entity management ──

    def add_entity(self, entity_id: str, label: str, **attrs: Any) -> None:
        """Add or update a node in the knowledge graph."""
        self.nodes[entity_id] = {"id": entity_id, "label": label, **attrs}

    def remove_entity(self, entity_id: str) -> bool:
        """Remove an entity and all its edges. Returns True if removed."""
        if entity_id not in self.nodes:
            return False
        del self.nodes[entity_id]
        self.edges = [
            e for e in self.edges
            if e.get("source") != entity_id and e.get("target") != entity_id
        ]
        return True

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        """Retrieve an entity by ID."""
        return self.nodes.get(entity_id)

    # ── Relation management ──

    def add_relation(self, source: str, relation: str, target: str, **attrs: Any) -> None:
        """Add a typed edge from source entity to target entity."""
        self.edges.append({
            "source": source,
            "relation": relation,
            "target": target,
            **attrs,
        })

    # ── Query ──

    def query_related(self, entity_id: str, max_depth: int = 2) -> dict[str, Any]:
        """Return the subgraph centered on an entity up to max_depth hops.

        Returns a dict with 'nodes' and 'edges' keys.
        """
        if entity_id not in self.nodes:
            return {"nodes": {}, "edges": []}

        visited_nodes: dict[str, dict[str, Any]] = {}
        visited_edges: list[dict[str, Any]] = []

        # BFS traversal
        frontier = {entity_id}
        for _ in range(max_depth):
            next_frontier: set[str] = set()
            for node_id in frontier:
                if node_id in visited_nodes:
                    continue
                if node_id in self.nodes:
                    visited_nodes[node_id] = dict(self.nodes[node_id])
                # Find all edges connected to this node
                for edge in self.edges:
                    src = edge.get("source", "")
                    tgt = edge.get("target", "")
                    if src == node_id or tgt == node_id:
                        if edge not in visited_edges:
                            visited_edges.append(dict(edge))
                        if src == node_id and tgt not in visited_nodes:
                            next_frontier.add(tgt)
                        if tgt == node_id and src not in visited_nodes:
                            next_frontier.add(src)
            frontier = next_frontier
            if not frontier:
                break

        return {"nodes": visited_nodes, "edges": visited_edges}

    def search_label(self, query: str) -> list[dict[str, Any]]:
        """Find entities whose label contains the query string (case-insensitive)."""
        q = query.lower()
        return [
            dict(node) for node in self.nodes.values()
            if q in str(node.get("label", "")).lower()
        ]

    # ── Persistence ──

    def snapshot(self) -> dict[str, Any]:
        """Return the full graph as a dict for serialization."""
        return {
            "nodes": dict(self.nodes),
            "edges": [dict(e) for e in self.edges],
        }

    def save(self) -> None:
        """Persist the graph to disk as JSON."""
        if self._store_path:
            self._store_path.write_text(
                json.dumps(self.snapshot(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _load(self) -> None:
        """Load the graph from disk."""
        if self._store_path and self._store_path.exists():
            try:
                data = json.loads(self._store_path.read_text(encoding="utf-8"))
                self.nodes = data.get("nodes", {})
                # Convert keys back to proper types
                self.nodes = {str(k): dict(v) for k, v in self.nodes.items()}
                self.edges = [dict(e) for e in data.get("edges", [])]
            except (json.JSONDecodeError, OSError):
                self.nodes = {}
                self.edges = []
