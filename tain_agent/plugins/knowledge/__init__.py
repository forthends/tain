"""KnowledgePlugin — double-layer knowledge management.

Dynamic layer : Temporary facts being explored (list of dicts)
Graph layer   : Persisted, stable knowledge (KnowledgeGraph)
"""

from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol
from tain_agent.plugins.knowledge.graph import KnowledgeGraph, KnowledgeSnapshot

logger = logging.getLogger(__name__)


class KnowledgePlugin:
    """Plugin that manages the agent's knowledge as a double-layer system.

    Double-layer design:
      - _dynamic: Temporary/hypothesis facts (list of dicts), not yet
        promoted to stable knowledge.
      - _graph: Persisted KnowledgeGraph — the agent's stable knowledge.

    Required PluginProtocol methods: initialize, shutdown, health_check,
    snapshot, restore.
    Optional PRAL hooks: on_cycle_start, on_cycle_end, enrich_prompt,
    on_llm_response.
    """

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._dynamic: list[dict[str, Any]] = []
        self._graph: KnowledgeGraph = KnowledgeGraph()
        self._persist_path: Path | None = None

    # ── PluginProtocol ──────────────────────────────────────────────

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        self._persist_path = ctx.workspace_path / "knowledge" / "graph.json"
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def shutdown(self) -> None:
        self._save()
        self._dynamic.clear()
        self._graph = KnowledgeGraph()
        self._ctx = None

    def health_check(self) -> HealthStatus:
        if self._ctx is None:
            return HealthStatus(status="critical", alerts=["not initialized"])
        metrics = {
            "dynamic_facts": float(len(self._dynamic)),
            "stable_entities": float(self._graph.entity_count),
            "stable_relations": float(self._graph.relation_count),
        }
        return HealthStatus(status="ok", metrics=metrics)

    def snapshot(self) -> dict[str, Any]:
        return {
            "dynamic": list(self._dynamic),
            "graph": self._graph.to_dict(),
        }

    def restore(self, data: dict[str, Any]) -> None:
        if "dynamic" in data:
            self._dynamic = list(data["dynamic"])
        if "graph" in data:
            self._graph = KnowledgeGraph.from_dict(data["graph"])

    # ── PRAL hooks ──────────────────────────────────────────────────

    def on_cycle_start(self, cycle: int) -> None:
        pass

    def on_cycle_end(self, cycle: int) -> None:
        self.consolidate()

    def enrich_prompt(self, base: str) -> str:
        """Inject recent knowledge facts into the prompt."""
        if self._graph.entity_count == 0 and len(self._dynamic) == 0:
            return base

        parts = [base, "", "## 知识图谱背景 (Knowledge Graph)"]

        # Show up to 10 stable entities
        entities = list(self._graph._entities.values())[:10]
        for e in entities:
            props = ", ".join(f"{k}={v}" for k, v in e.properties.items())
            parts.append(f"- {e.label} ({e.entity_id})" + (f" [{props}]" if props else ""))

        # Show up to 5 dynamic facts
        if self._dynamic:
            parts.append("")
            parts.append("### 待确认的事实 (Unconfirmed Facts)")
            for fact in self._dynamic[:5]:
                parts.append(
                    f"- {fact.get('subject', '?')} "
                    f"{fact.get('predicate', '?')} "
                    f"{fact.get('object', '?')}"
                )

        return "\n".join(parts)

    def on_llm_response(self, response: Any) -> None:
        pass

    # ── Persistence ─────────────────────────────────────────────────

    def _save(self) -> None:
        if self._persist_path is None:
            return
        try:
            self._persist_path.write_text(
                json.dumps(self._graph.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save knowledge graph: %s", e)

    def _load(self) -> None:
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            self._graph = KnowledgeGraph.from_dict(data)
        except Exception as e:
            logger.warning("Failed to load knowledge graph: %s — starting fresh", e)
            self._graph = KnowledgeGraph()

    # ── Knowledge API ───────────────────────────────────────────────

    def query(
        self, entity_id: str, max_depth: int = 2, include_dynamic: bool = True
    ) -> dict[str, Any]:
        """Query the knowledge graph around an entity.

        Args:
            entity_id: The entity to query.
            max_depth: Maximum hops from the entity.
            include_dynamic: Whether to include dynamic facts in the result.

        Returns dict with 'nodes', 'edges', and optionally 'dynamic_facts'.
        """
        result = self._graph.query(entity_id, max_depth=max_depth)

        if include_dynamic:
            relevant_dynamic = [
                f for f in self._dynamic
                if f.get("subject") == entity_id or f.get("object") == entity_id
            ]
            result["dynamic_facts"] = relevant_dynamic

        return result

    def ingest(
        self,
        fact: str | dict[str, Any],
        to_stable: bool = False,
    ) -> None:
        """Ingest a new fact into the knowledge system.

        Args:
            fact: A string "subject predicate object" or a dict with
                  subject/predicate/object keys.
            to_stable: If True, add directly to the stable graph as well.
        """
        if isinstance(fact, str):
            parts = fact.split(maxsplit=2)
            if len(parts) < 3:
                fact_dict = {"raw": fact, "subject": "", "predicate": "", "object": ""}
            else:
                fact_dict = {
                    "subject": parts[0],
                    "predicate": parts[1],
                    "object": parts[2],
                }
        else:
            fact_dict = dict(fact)

        self._dynamic.append(fact_dict)

        if to_stable:
            subj = fact_dict.get("subject", "")
            pred = fact_dict.get("predicate", "")
            obj = fact_dict.get("object", "")
            if subj and pred and obj:
                self._graph.add_entity(subj, subj)
                self._graph.add_entity(obj, obj)
                self._graph.add_relation(subj, pred, obj)

    def add_dynamic(self, fact: dict[str, Any]) -> None:
        """Add a fact to the dynamic layer only."""
        self._dynamic.append(dict(fact))

    def consolidate(self, min_confidence: float = 0.5) -> int:
        """Promote dynamic facts to the stable graph. Returns count promoted.

        A dynamic fact is promoted if:
          - It appears at least 2 times (repeated observation), OR
          - It has a confidence score >= min_confidence.

        Promoted facts are removed from the dynamic layer.
        """
        promoted = 0
        kept: list[dict[str, Any]] = []

        # Count occurrences of each unique fact
        from collections import Counter
        fact_keys: list[tuple] = []
        for f in self._dynamic:
            key = (f.get("subject", ""), f.get("predicate", ""), f.get("object", ""))
            fact_keys.append(key)

        counts = Counter(fact_keys)

        for fact in self._dynamic:
            key = (fact.get("subject", ""), fact.get("predicate", ""), fact.get("object", ""))
            confidence = float(fact.get("confidence", 0.0))

            if counts[key] >= 2 or confidence >= min_confidence:
                subj = fact.get("subject", "")
                pred = fact.get("predicate", "")
                obj = fact.get("object", "")
                if subj and pred and obj:
                    self._graph.add_entity(subj, subj)
                    self._graph.add_entity(obj, obj)
                    self._graph.add_relation(subj, pred, obj)
                    promoted += 1
            else:
                kept.append(fact)

        self._dynamic = kept
        return promoted

    def export_subgraph(self, entity_ids: list[str]) -> dict[str, Any]:
        """Export a subgraph containing the specified entities and their
        immediate relations. Suitable for sharing with other agents."""
        subgraph: dict[str, Any] = {"entities": {}, "relations": []}
        entity_set = set(entity_ids)

        for eid in entity_ids:
            if eid in self._graph._entities:
                subgraph["entities"][eid] = {
                    "label": self._graph._entities[eid].label,
                    "properties": self._graph._entities[eid].properties,
                }

        for rel in self._graph._relations:
            if rel.source in entity_set or rel.target in entity_set:
                subgraph["relations"].append({
                    "source": rel.source,
                    "relation": rel.relation,
                    "target": rel.target,
                })
                entity_set.add(rel.source)
                entity_set.add(rel.target)

        # Also include entities discovered via relations
        for eid in entity_set:
            if eid not in subgraph["entities"] and eid in self._graph._entities:
                e = self._graph._entities[eid]
                subgraph["entities"][eid] = {
                    "label": e.label,
                    "properties": e.properties,
                }

        return subgraph
