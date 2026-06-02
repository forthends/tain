"""KnowledgeGraph — dict-based graph store for entities and relations."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Entity:
    """A knowledge entity — a concept, object, or fact the agent knows."""

    entity_id: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


@dataclass
class Relation:
    """A directed, typed relation between two entities."""

    source: str
    relation: str
    target: str
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)


@dataclass
class KnowledgeSnapshot:
    """A point-in-time snapshot of the knowledge graph."""

    entities: dict[str, Entity]
    relations: list[Relation]
    timestamp: str = field(default_factory=_now)


class KnowledgeGraph:
    """Dict-based graph store for managing entities and relations.

    Used as the persistent/stable store within KnowledgePlugin.
    """

    def __init__(self):
        self._entities: dict[str, Entity] = {}
        self._relations: list[Relation] = []

    # ── Entity CRUD ─────────────────────────────────────────────────

    def add_entity(self, entity_id: str, label: str, **properties: Any) -> Entity:
        """Add or update an entity. Returns the entity."""
        if entity_id in self._entities:
            existing = self._entities[entity_id]
            existing.label = label
            existing.properties.update(properties)
            existing.updated_at = _now()
            return existing

        entity = Entity(
            entity_id=entity_id,
            label=label,
            properties=dict(properties),
        )
        self._entities[entity_id] = entity
        return entity

    def get_entity(self, entity_id: str) -> Entity | None:
        """Get an entity by ID, or None."""
        return self._entities.get(entity_id)

    def remove_entity(self, entity_id: str) -> bool:
        """Remove an entity and all its incident relations. Returns True if found."""
        if entity_id not in self._entities:
            return False
        del self._entities[entity_id]
        self._relations = [
            r for r in self._relations
            if r.source != entity_id and r.target != entity_id
        ]
        return True

    # ── Relations ───────────────────────────────────────────────────

    def add_relation(
        self,
        source: str,
        relation: str,
        target: str,
        **properties: Any,
    ) -> Relation:
        """Add a typed relation between two entities. Creates entities if missing."""
        if source not in self._entities:
            self.add_entity(source, source)
        if target not in self._entities:
            self.add_entity(target, target)

        rel = Relation(
            source=source,
            relation=relation,
            target=target,
            properties=dict(properties),
        )
        self._relations.append(rel)
        return rel

    def query(self, entity_id: str, max_depth: int = 2) -> dict[str, Any]:
        """Get the subgraph centred on an entity up to max_depth hops.

        Returns a dict with 'nodes' (dict of entity_id -> Entity) and
        'edges' (list of Relation dicts).
        """
        if entity_id not in self._entities:
            return {"nodes": {}, "edges": []}

        visited: set[str] = set()
        frontier = {entity_id}
        nodes: dict[str, Entity] = {}
        edges: list[dict] = []

        for _ in range(max_depth + 1):
            next_frontier: set[str] = set()
            for eid in frontier:
                if eid in visited:
                    continue
                visited.add(eid)
                if eid in self._entities:
                    nodes[eid] = self._entities[eid]
            for rel in self._relations:
                if rel.source in frontier and rel.target not in visited:
                    edges.append({
                        "source": rel.source,
                        "relation": rel.relation,
                        "target": rel.target,
                        "properties": rel.properties,
                    })
                    next_frontier.add(rel.target)
                elif rel.target in frontier and rel.source not in visited:
                    edges.append({
                        "source": rel.source,
                        "relation": rel.relation,
                        "target": rel.target,
                        "properties": rel.properties,
                    })
                    next_frontier.add(rel.source)
            frontier = next_frontier
            if not frontier:
                break

        return {
            "nodes": {eid: e for eid, e in nodes.items()},
            "edges": edges,
        }

    def find_contradictions(
        self, subject: str, predicate: str, obj: str
    ) -> list[Relation]:
        """Find relations that contradict a proposed fact.

        Contradiction check: any existing relation with the same (subject,
        predicate) but a different target, or (subject, opposite_predicate)
        with the same target.
        """
        contradictions: list[Relation] = []
        for rel in self._relations:
            # Same subject + predicate, different object
            if rel.source == subject and rel.relation == predicate and rel.target != obj:
                contradictions.append(rel)
            # Opposite direction with negation-style predicates
            if (
                rel.source == obj
                and rel.target == subject
                and self._are_contradictory(rel.relation, predicate)
            ):
                contradictions.append(rel)
        return contradictions

    @staticmethod
    def _are_contradictory(pred1: str, pred2: str) -> bool:
        """Check if two predicates are contradictory."""
        opposites = {
            "is": "is_not",
            "has": "lacks",
            "supports": "opposes",
            "loves": "hates",
            "believes": "disbelieves",
        }
        inverted = {v: k for k, v in opposites.items()}
        merged = {**opposites, **inverted}
        return merged.get(pred1) == pred2

    # ── Bulk operations ─────────────────────────────────────────────

    def snapshot(self) -> KnowledgeSnapshot:
        """Create a point-in-time snapshot of the graph."""
        return KnowledgeSnapshot(
            entities=dict(self._entities),
            relations=list(self._relations),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the graph to a plain dict for JSON persistence."""
        import dataclasses
        return {
            "entities": {
                eid: dataclasses.asdict(e)
                for eid, e in self._entities.items()
            },
            "relations": [dataclasses.asdict(r) for r in self._relations],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeGraph":
        """Deserialize a graph from a plain dict."""
        graph = cls()
        for eid, edata in data.get("entities", {}).items():
            graph._entities[eid] = Entity(**edata)
        for rdata in data.get("relations", []):
            graph._relations.append(Relation(**rdata))
        return graph

    @property
    def entity_count(self) -> int:
        return len(self._entities)

    @property
    def relation_count(self) -> int:
        return len(self._relations)
