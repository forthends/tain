"""Tests for MemoryPlugin — decay engine, episodic store, semantic store."""

import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from tain_agent.kernel.protocol import AgentContext, PluginProtocol
from tain_agent.plugins.memory import MemoryPlugin
from tain_agent.plugins.memory.decay import (
    current_strength,
    decay_rate,
    should_forget,
)
from tain_agent.plugins.memory.episodic import EpisodicMemory, EpisodicStore
from tain_agent.plugins.memory.semantic import SemanticStore


# ── Decay Engine ──────────────────────────────────────────────────────

class TestDecay:
    def test_high_importance_slow_decay(self):
        """High importance memories should decay very slowly."""
        rate_high = decay_rate(0.95)
        rate_low = decay_rate(0.05)
        assert rate_high < rate_low
        assert rate_high < 0.05  # near-zero for high importance

    def test_new_memory_has_high_strength(self):
        """A freshly created memory should have strength close to its importance."""
        now = datetime.now(timezone.utc).isoformat()
        strength = current_strength(importance=0.8, created_at=now, recall_count=0)
        assert 0.70 <= strength <= 0.85

    def test_old_memory_decays(self):
        """A very old memory should have low strength."""
        old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        strength = current_strength(importance=0.5, created_at=old, recall_count=0)
        assert strength < 0.3

    def test_forget_threshold(self):
        """Memories below threshold should be flagged for forgetting."""
        # Very old, low importance = very weak
        old = (datetime.now(timezone.utc) - timedelta(days=1000)).isoformat()
        strength = current_strength(importance=0.01, created_at=old, recall_count=0)
        assert should_forget(strength, threshold=0.05)

    def test_recall_slows_decay(self):
        """Recalling a memory should increase its strength via the bonus."""
        now = datetime.now(timezone.utc).isoformat()
        without_recall = current_strength(importance=0.5, created_at=now, recall_count=0)
        with_recall = current_strength(importance=0.5, created_at=now, recall_count=5,
                                       last_recalled_at=now)
        assert with_recall > without_recall

    def test_decay_rate_non_negative(self):
        """Decay rate should never be negative."""
        for imp in [0.0, 0.25, 0.5, 0.75, 1.0]:
            assert decay_rate(imp) >= 0.0

    def test_strength_range(self):
        """Strength should be between 0 and 1 for reasonable inputs."""
        now = datetime.now(timezone.utc).isoformat()
        for imp in [0.1, 0.5, 0.9]:
            s = current_strength(importance=imp, created_at=now, recall_count=0)
            assert 0.0 <= s <= 1.0


# ── EpisodicMemory ────────────────────────────────────────────────────

class TestEpisodicMemory:
    def test_recall_increments_count(self):
        mem = EpisodicMemory(content="test memory", importance=0.6)
        assert mem.recall_count == 0
        mem.recall()
        assert mem.recall_count == 1
        mem.recall()
        assert mem.recall_count == 2
        assert mem.last_recalled_at is not None

    def test_roundtrip_dict(self):
        mem = EpisodicMemory(
            content="learned something",
            importance=0.7,
            associations=["topic_a", "topic_b"],
        )
        d = mem.to_dict()
        restored = EpisodicMemory.from_dict(d)
        assert restored.content == "learned something"
        assert restored.importance == 0.7
        assert restored.associations == ["topic_a", "topic_b"]
        assert restored.memory_id == mem.memory_id

    def test_strength_decreases_over_time(self):
        old = EpisodicMemory(
            content="old memory",
            importance=0.5,
            created_at=(datetime.now(timezone.utc) - timedelta(days=100)).isoformat(),
        )
        new = EpisodicMemory(
            content="new memory",
            importance=0.5,
        )
        assert old.strength() < new.strength()

    def test_default_values(self):
        mem = EpisodicMemory(content="test")
        assert mem.importance == 0.5
        assert mem.recall_count == 0
        assert mem.associations == []
        assert mem.memory_id != ""


# ── EpisodicStore ─────────────────────────────────────────────────────

class TestEpisodicStore:
    def test_encode_and_recall(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_episodic.db"
            store = EpisodicStore(db_path)
            store.initialize()

            store.encode(EpisodicMemory(content="memory 1", importance=0.9))
            store.encode(EpisodicMemory(content="memory 2", importance=0.3))

            results = store.recall(limit=10)
            assert len(results) == 2
            # Higher importance first
            assert results[0].content == "memory 1"
            assert results[1].content == "memory 2"

            store.shutdown()

    def test_forget_weak_memories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_episodic.db"
            store = EpisodicStore(db_path)
            store.initialize()

            # Strong memory
            store.encode(EpisodicMemory(content="important", importance=0.95))
            # Weak memory: old + low importance
            old = (datetime.now(timezone.utc) - timedelta(days=500)).isoformat()
            store.encode(EpisodicMemory(
                content="forgettable",
                importance=0.01,
                created_at=old,
            ))

            assert store.count() == 2
            forgotten = store.forget(threshold=0.05)
            assert forgotten >= 1  # at least the weak one is gone
            remaining = store.recall(limit=10)
            assert all(m.content == "important" for m in remaining)
            assert len(remaining) == store.count()

            store.shutdown()

    def test_reinforce_increments_recall(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_episodic.db"
            store = EpisodicStore(db_path)
            store.initialize()

            mem = EpisodicMemory(content="test reinforce", importance=0.5)
            mid = store.encode(mem)

            reinforced = store.reinforce(mid)
            assert reinforced is not None
            assert reinforced.recall_count == 1
            assert reinforced.last_recalled_at is not None

            # Fetch again to verify persistence
            fetched = store.get(mid)
            assert fetched is not None
            assert fetched.recall_count == 1

            store.shutdown()

    def test_recent_ordering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_episodic.db"
            store = EpisodicStore(db_path)
            store.initialize()

            m1 = EpisodicMemory(content="first", importance=0.5)
            m2 = EpisodicMemory(content="second", importance=0.5)
            store.encode(m1)
            store.encode(m2)

            recent = store.recent(limit=10)
            assert len(recent) == 2
            assert recent[0].content == "second"  # most recent first

            store.shutdown()

    def test_get_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_episodic.db"
            store = EpisodicStore(db_path)
            store.initialize()

            assert store.get("nonexistent-id") is None
            assert store.reinforce("nonexistent-id") is None

            store.shutdown()


# ── SemanticStore ─────────────────────────────────────────────────────

class TestSemanticStore:
    def test_add_and_get_entity(self):
        store = SemanticStore()
        store.add_entity("python", "Python", type="language", version="3.12")
        entity = store.get_entity("python")
        assert entity is not None
        assert entity["label"] == "Python"
        assert entity["type"] == "language"

    def test_add_relation(self):
        store = SemanticStore()
        store.add_entity("python", "Python")
        store.add_entity("fastapi", "FastAPI")
        store.add_relation("fastapi", "built_with", "python")

        assert len(store.edges) == 1
        assert store.edges[0]["source"] == "fastapi"
        assert store.edges[0]["relation"] == "built_with"

    def test_query_related(self):
        store = SemanticStore()
        store.add_entity("python", "Python")
        store.add_entity("fastapi", "FastAPI")
        store.add_entity("django", "Django")
        store.add_relation("fastapi", "built_with", "python")
        store.add_relation("django", "built_with", "python")

        result = store.query_related("python")
        assert len(result["nodes"]) >= 1  # python at minimum
        assert len(result["edges"]) >= 1

    def test_remove_entity_cleans_edges(self):
        store = SemanticStore()
        store.add_entity("a", "A")
        store.add_entity("b", "B")
        store.add_relation("a", "knows", "b")

        assert len(store.edges) == 1
        store.remove_entity("a")
        assert store.get_entity("a") is None
        assert len(store.edges) == 0

    def test_search_label(self):
        store = SemanticStore()
        store.add_entity("py", "Python programming")
        store.add_entity("js", "JavaScript")
        store.add_entity("rs", "Rust systems")

        results = store.search_label("python")
        assert len(results) == 1
        assert results[0]["id"] == "py"

    def test_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "semantic.json"
            store = SemanticStore(store_path)
            store.initialize()
            store.add_entity("test", "TestEntity", type="concept")
            store.add_relation("test", "is_a", "concept")
            store.save()

            # Load into a new store
            store2 = SemanticStore(store_path)
            store2.initialize()
            assert "test" in store2.nodes
            assert len(store2.edges) == 1


# ── MemoryPlugin ──────────────────────────────────────────────────────

class TestMemoryPlugin:
    def _make_ctx(self, tmpdir):
        return AgentContext(
            agent_name="test",
            agent_id="m1",
            evolution_mode="chaos",
            workspace_path=Path(tmpdir),
            config={},
            kernel_version="0.6.0",
        )

    def test_satisfies_protocol(self):
        assert isinstance(MemoryPlugin(), PluginProtocol)

    def test_initialize_and_shutdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = MemoryPlugin()
            plugin.initialize(ctx)
            assert plugin.health_check().status in ("ok", "warning")
            plugin.shutdown()

    def test_encode_and_recall(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = MemoryPlugin()
            plugin.initialize(ctx)

            plugin.encode("test memory 1", importance=0.9)
            plugin.encode("test memory 2", importance=0.3)

            results = plugin.recall(limit=10)
            assert len(results) >= 2
            assert results[0].content == "test memory 1"

            plugin.shutdown()

    def test_recent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = MemoryPlugin()
            plugin.initialize(ctx)

            plugin.encode("first")
            plugin.encode("second")

            recent = plugin.recent(limit=5)
            assert len(recent) >= 2
            assert recent[0].content == "second"

            plugin.shutdown()

    def test_reinforce(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = MemoryPlugin()
            plugin.initialize(ctx)

            mem = plugin.encode("to reinforce", importance=0.5)
            reinforced = plugin.reinforce(mem.memory_id)
            assert reinforced is not None
            assert reinforced.recall_count == 1

            plugin.shutdown()

    def test_consolidate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = MemoryPlugin()
            plugin.initialize(ctx)

            # Add a memory that will stay
            plugin.encode("important memory", importance=0.95)
            # Add an old, weak memory
            old_ts = (datetime.now(timezone.utc) - timedelta(days=1000)).isoformat()
            old_mem = EpisodicMemory(content="weak old memory", importance=0.01, created_at=old_ts)
            plugin._episodic.encode(old_mem)  # type: ignore[union-attr]

            forgotten = plugin.consolidate(threshold=0.05)
            assert forgotten >= 1

            remaining = plugin.recall(limit=10)
            assert all("important" in m.content for m in remaining)

            plugin.shutdown()

    def test_enrich_prompt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = MemoryPlugin()
            plugin.initialize(ctx)

            plugin.encode("Learned about Python async patterns", importance=0.8)
            result = plugin.enrich_prompt("base prompt")
            assert "base prompt" in result
            assert "## 最近的记忆" in result
            assert "Python async patterns" in result

            plugin.shutdown()

    def test_working_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = MemoryPlugin()
            plugin.initialize(ctx)

            plugin.add_to_working("observation", "The user prefers concise answers")
            ctx_str = plugin.get_working_context()
            assert "concise answers" in ctx_str

            plugin.shutdown()

    def test_semantic_operations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = MemoryPlugin()
            plugin.initialize(ctx)

            plugin.add_entity("postgres", "PostgreSQL", type="database")
            plugin.add_relation("postgres", "used_for", "data_storage")
            result = plugin.query_related("postgres")
            assert "postgres" in result["nodes"]

            plugin.shutdown()

    def test_summarize(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = MemoryPlugin()
            plugin.initialize(ctx)

            plugin.encode("test memory for summary", importance=0.7)
            plugin.add_entity("test_entity", "Test Entity")
            plugin.add_to_working("test", "working item")

            summary = plugin.summarize()
            assert summary["working_items"] == 1
            assert summary["episodic_count"] >= 1
            assert summary["semantic_entities"] >= 1

            plugin.shutdown()

    def test_full_lifecycle_chaos_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = AgentContext(
                agent_name="lifecycle_test",
                agent_id="lc1",
                evolution_mode="chaos",
                workspace_path=Path(tmpdir),
                config={},
                kernel_version="0.6.0",
            )
            plugin = MemoryPlugin()
            plugin.initialize(ctx)

            # Simulate a PRAL cycle
            plugin.on_cycle_start(1)
            plugin.encode("Phase 2 memory implementation", importance=0.85)
            plugin.add_entity("memory_plugin", "MemoryPlugin", type="component")
            plugin.on_cycle_end(1)

            # Verify persistence
            db_file = Path(tmpdir) / "memory" / "episodic.db"
            json_file = Path(tmpdir) / "memory" / "semantic.json"
            assert db_file.exists()
            assert json_file.exists()

            summary = plugin.summarize()
            assert summary["episodic_count"] >= 1
            assert summary["semantic_entities"] >= 1

            plugin.shutdown()

    def test_specified_mode_with_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = AgentContext(
                agent_name="spec_test",
                agent_id="s1",
                evolution_mode="specified",
                workspace_path=Path(tmpdir),
                config={"memory": {"consolidation_threshold": 0.1}},
                kernel_version="0.6.0",
            )
            plugin = MemoryPlugin()
            plugin.initialize(ctx)

            plugin.encode("Important specified memory", importance=0.9)
            results = plugin.recall(limit=5)
            assert len(results) == 1

            plugin.shutdown()
