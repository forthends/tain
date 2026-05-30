"""MemoryPlugin — biomimetic three-tier memory system.

Working Memory  : In-memory list of recent interactions (session-scoped)
Episodic Memory : SQLite-backed store with decay-based forgetting
Semantic Memory : JSON-backed knowledge graph of entities and relations
"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Any

from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol
from tain_agent.plugins.memory.episodic import EpisodicMemory, EpisodicStore
from tain_agent.plugins.memory.semantic import SemanticStore

logger = logging.getLogger(__name__)


class MemoryPlugin:
    """Plugin that manages the agent's memory across three tiers."""

    MAX_WORKING_MEMORY = 20

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._episodic: EpisodicStore | None = None
        self._semantic: SemanticStore | None = None
        self._working: list[dict[str, Any]] = []

    # ── PluginProtocol ───────────────────────────────────────────

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx

        # Episodic store — SQLite file in workspace
        episodic_path = ctx.workspace_path / "memory" / "episodic.db"
        self._episodic = EpisodicStore(episodic_path)
        self._episodic.initialize()

        # Semantic store — JSON file in workspace
        semantic_path = ctx.workspace_path / "memory" / "semantic.json"
        self._semantic = SemanticStore(semantic_path)
        self._semantic.initialize()

        self._working = []

    def shutdown(self) -> None:
        if self._episodic:
            self._episodic.shutdown()
        if self._semantic:
            self._semantic.shutdown()
        self._working.clear()

    def health_check(self) -> HealthStatus:
        alerts: list[str] = []
        metrics: dict[str, float] = {}

        if self._episodic is None:
            alerts.append("episodic store not initialized")
        else:
            ep_status = self._episodic.health_check()
            if ep_status != "ok":
                alerts.append(f"episodic store: {ep_status}")
            metrics["episodic_count"] = float(self._episodic.count())

        if self._semantic is None:
            alerts.append("semantic store not initialized")
        else:
            sem_status = self._semantic.health_check()
            if sem_status != "ok":
                alerts.append(f"semantic store: {sem_status}")
            metrics["semantic_nodes"] = float(len(self._semantic.nodes))
            metrics["semantic_edges"] = float(len(self._semantic.edges))

        metrics["working_memory_items"] = float(len(self._working))

        if alerts:
            return HealthStatus(status="warning", metrics=metrics, alerts=alerts)
        return HealthStatus(status="ok", metrics=metrics)

    def snapshot(self) -> dict[str, Any]:
        return {
            "working": list(self._working),
            "episodic": self._episodic.snapshot() if self._episodic else [],
            "semantic": self._semantic.snapshot() if self._semantic else {},
        }

    def restore(self, data: dict[str, Any]) -> None:
        """Restore memory state from a snapshot. Skips SQLite for episodic."""
        if "working" in data:
            self._working = list(data["working"])
        if "semantic" in data and self._semantic:
            self._semantic.nodes = data["semantic"].get("nodes", {})
            self._semantic.edges = data["semantic"].get("edges", [])

    # ── PRAL hooks ──

    def on_cycle_start(self, cycle: int) -> None:
        """Consolidate memories at the start of each PRAL cycle."""
        self.consolidate()

    def on_cycle_end(self, cycle: int) -> None:
        """Persist all stores at cycle end."""
        if self._semantic:
            self._semantic.save()

    def enrich_prompt(self, base: str) -> str:
        """Append recent episodic memories to the system prompt."""
        if self._episodic is None:
            return base

        memories = self._episodic.recall(limit=5)
        if not memories:
            return base

        parts = [base, "", "## 最近的记忆"]
        for i, mem in enumerate(memories, 1):
            parts.append(f"{i}. {mem.content} (strength: {mem.strength():.4f})")

        return "\n".join(parts)

    def on_llm_response(self, response: Any) -> None:
        """Optionally encode LLM responses as episodic memories."""
        # Check if the response has text content worth remembering
        text = ""
        if hasattr(response, "text_blocks"):
            text = " ".join(str(b) for b in response.text_blocks if hasattr(b, "text"))
        elif hasattr(response, "content"):
            text = str(response.content)
        elif isinstance(response, str):
            text = response

        if len(text) > 20:
            self.add_to_working("llm_response", text[:500])

    # ── Working Memory ───────────────────────────────────────────

    def add_to_working(self, category: str, content: str, metadata: dict | None = None) -> None:
        """Add an item to working memory, evicting oldest if at capacity."""
        self._working.append({
            "category": category,
            "content": content,
            "metadata": metadata or {},
        })
        while len(self._working) > self.MAX_WORKING_MEMORY:
            self._working.pop(0)

    def get_working_context(self, limit: int = 5) -> str:
        """Return recent working memory items as context string."""
        recent = self._working[-limit:]
        if not recent:
            return ""
        lines = ["## 工作记忆"]
        for item in recent:
            lines.append(f"- [{item['category']}] {item['content'][:200]}")
        return "\n".join(lines)

    # ── Episodic Memory ──────────────────────────────────────────

    def encode(self, content: str, importance: float = 0.5,
               associations: list[str] | None = None) -> EpisodicMemory:
        """Create and store a new episodic memory."""
        if self._episodic is None:
            raise RuntimeError("MemoryPlugin not initialized — no episodic store")
        memory = EpisodicMemory(
            content=content,
            importance=max(0.0, min(1.0, importance)),
            associations=associations or [],
        )
        self._episodic.encode(memory)
        return memory

    def recall(self, limit: int = 10, min_strength: float = 0.0) -> list[EpisodicMemory]:
        """Recall episodic memories ordered by strength."""
        if self._episodic is None:
            return []
        return self._episodic.recall(limit=limit, min_strength=min_strength)

    def recent(self, limit: int = 10) -> list[EpisodicMemory]:
        """Get most recently created episodic memories."""
        if self._episodic is None:
            return []
        return self._episodic.recent(limit=limit)

    def reinforce(self, memory_id: str) -> EpisodicMemory | None:
        """Reinforce a specific episodic memory by recording a recall."""
        if self._episodic is None:
            return None
        return self._episodic.reinforce(memory_id)

    # ── Semantic Memory ──────────────────────────────────────────

    def add_entity(self, entity_id: str, label: str, **attrs: Any) -> None:
        """Add or update a semantic entity."""
        if self._semantic:
            self._semantic.add_entity(entity_id, label, **attrs)

    def add_relation(self, source: str, relation: str, target: str, **attrs: Any) -> None:
        """Add a typed relation between entities."""
        if self._semantic:
            self._semantic.add_relation(source, relation, target, **attrs)

    def query_related(self, entity_id: str, max_depth: int = 2) -> dict[str, Any]:
        """Query the subgraph around an entity."""
        if self._semantic is None:
            return {"nodes": {}, "edges": []}
        return self._semantic.query_related(entity_id, max_depth=max_depth)

    # ── Maintenance ──────────────────────────────────────────────

    def consolidate(self, threshold: float = 0.05) -> int:
        """Forget weak memories below the strength threshold. Returns count forgotten."""
        if self._episodic is None:
            return 0
        forgotten = self._episodic.forget(threshold=threshold)
        if forgotten > 0:
            logger.info("Consolidated %d weak episodic memories", forgotten)
        return forgotten

    def summarize(self, limit: int = 10) -> dict[str, Any]:
        """Return a multi-tier summary of the agent's memory state."""
        episodic_memories = self.recall(limit=limit) if self._episodic else []
        return {
            "working_items": len(self._working),
            "working_preview": [w["content"][:100] for w in self._working[-3:]],
            "episodic_count": self._episodic.count() if self._episodic else 0,
            "top_episodic": [
                {"content": m.content[:100], "strength": m.strength()}
                for m in episodic_memories
            ],
            "semantic_entities": len(self._semantic.nodes) if self._semantic else 0,
            "semantic_relations": len(self._semantic.edges) if self._semantic else 0,
        }
