"""Tests for KnowledgePlugin — graph, lifecycle, and plugin integration."""

import tempfile
from pathlib import Path

from tain_agent.kernel.protocol import AgentContext, PluginProtocol
from tain_agent.plugins.knowledge import KnowledgePlugin
from tain_agent.plugins.knowledge.graph import KnowledgeGraph, Entity, Relation
from tain_agent.plugins.knowledge.lifecycle import (
    _project_root,
    add_reference,
    conflict_detect,
    freshness_check,
    get_referenced_files,
    inherit_entities,
    list_references,
    sync_references,
)


class TestKnowledgeGraph:
    """Tests for KnowledgeGraph — the dict-based graph store."""

    def test_add_and_get_entity(self):
        graph = KnowledgeGraph()
        entity = graph.add_entity("python", "Python", type="language", version="3.12")
        assert entity.entity_id == "python"
        assert entity.label == "Python"
        assert entity.properties["type"] == "language"

        retrieved = graph.get_entity("python")
        assert retrieved is not None
        assert retrieved.label == "Python"

    def test_query_entity_with_relations(self):
        graph = KnowledgeGraph()
        graph.add_entity("python", "Python")
        graph.add_entity("fastapi", "FastAPI")
        graph.add_relation("fastapi", "built_with", "python")

        result = graph.query("python")
        assert len(result["nodes"]) >= 1
        assert len(result["edges"]) >= 1

    def test_add_relation_creates_entities(self):
        graph = KnowledgeGraph()
        graph.add_relation("a", "knows", "b")
        assert graph.get_entity("a") is not None
        assert graph.get_entity("b") is not None

    def test_find_contradictions_same_predicate_different_target(self):
        graph = KnowledgeGraph()
        graph.add_relation("sky", "is", "blue")
        contradictions = graph.find_contradictions("sky", "is", "green")
        assert len(contradictions) == 1
        assert contradictions[0].target == "blue"

    def test_find_contradictions_no_conflict(self):
        graph = KnowledgeGraph()
        graph.add_relation("sky", "is", "blue")
        contradictions = graph.find_contradictions("sky", "is", "blue")
        assert len(contradictions) == 0

    def test_snapshot_and_from_dict_roundtrip(self):
        graph = KnowledgeGraph()
        graph.add_entity("x", "X", value=1)
        graph.add_relation("x", "relates_to", "y")
        snap = graph.snapshot()
        assert len(snap.entities) == 2  # x and y
        assert len(snap.relations) == 1

        data = graph.to_dict()
        restored = KnowledgeGraph.from_dict(data)
        assert restored.get_entity("x") is not None
        assert restored.relation_count == 1

    def test_remove_entity_cleans_edges(self):
        graph = KnowledgeGraph()
        graph.add_entity("a", "A")
        graph.add_entity("b", "B")
        graph.add_relation("a", "knows", "b")
        assert graph.relation_count == 1

        graph.remove_entity("a")
        assert graph.get_entity("a") is None
        assert graph.relation_count == 0


class TestLifecycle:
    """Tests for knowledge lifecycle functions."""

    def test_conflict_detect_different_object(self):
        existing = [
            {"subject": "sky", "predicate": "is", "object": "blue"},
        ]
        conflicts = conflict_detect(existing, "sky", "is", "green")
        assert len(conflicts) == 1
        assert conflicts[0]["object"] == "blue"

    def test_conflict_detect_opposite_predicate(self):
        existing = [
            {"subject": "sky", "predicate": "is_not", "object": "green"},
        ]
        conflicts = conflict_detect(existing, "sky", "is", "green")
        assert len(conflicts) >= 1

    def test_conflict_detect_no_conflict(self):
        existing = [
            {"subject": "sky", "predicate": "is", "object": "blue"},
        ]
        conflicts = conflict_detect(existing, "sky", "is", "blue")
        assert len(conflicts) == 0

    def test_freshness_check_recent(self):
        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        is_fresh, age = freshness_check(recent, max_age_days=30)
        assert is_fresh is True
        assert 4.0 < age < 6.0

    def test_freshness_check_stale(self):
        from datetime import datetime, timezone, timedelta
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        is_fresh, age = freshness_check(old, max_age_days=30)
        assert is_fresh is False
        assert age > 30


class TestKnowledgePlugin:
    """Tests for the KnowledgePlugin itself."""

    def _make_ctx(self, tmpdir):
        return AgentContext(
            agent_name="test",
            agent_id="k1",
            evolution_mode="chaos",
            workspace_path=Path(tmpdir),
            config={},
            kernel_version="0.6.0",
        )

    def test_satisfies_protocol(self):
        assert isinstance(KnowledgePlugin(), PluginProtocol)

    def test_initialize_and_shutdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = KnowledgePlugin()
            plugin.initialize(ctx)
            assert plugin.health_check().status == "ok"
            plugin.shutdown()
            assert plugin.health_check().status == "critical"

    def test_ingest_to_dynamic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = KnowledgePlugin()
            plugin.initialize(ctx)

            plugin.ingest({"subject": "earth", "predicate": "is", "object": "round"})
            assert len(plugin._dynamic) == 1

            plugin.shutdown()

    def test_ingest_to_stable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = KnowledgePlugin()
            plugin.initialize(ctx)

            plugin.ingest(
                {"subject": "water", "predicate": "is", "object": "wet"},
                to_stable=True,
            )
            assert plugin._graph.entity_count >= 1

            plugin.shutdown()

    def test_consolidate_promotes_repeated_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = KnowledgePlugin()
            plugin.initialize(ctx)

            # Add the same fact twice
            plugin.ingest({"subject": "fire", "predicate": "is", "object": "hot"})
            plugin.ingest({"subject": "fire", "predicate": "is", "object": "hot"})

            promoted = plugin.consolidate()
            assert promoted >= 1
            assert plugin._graph.entity_count >= 1

            plugin.shutdown()

    def test_query_returns_nodes_and_edges(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = KnowledgePlugin()
            plugin.initialize(ctx)

            plugin.ingest(
                {"subject": "python", "predicate": "is_a", "object": "language"},
                to_stable=True,
            )
            result = plugin.query("python")
            assert "nodes" in result
            assert "edges" in result

            plugin.shutdown()

    def test_export_subgraph(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = KnowledgePlugin()
            plugin.initialize(ctx)

            plugin.ingest(
                {"subject": "apple", "predicate": "is_a", "object": "fruit"},
                to_stable=True,
            )
            sub = plugin.export_subgraph(["apple"])
            assert "entities" in sub
            assert "apple" in sub["entities"]

            plugin.shutdown()

    def test_enrich_prompt_adds_knowledge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = KnowledgePlugin()
            plugin.initialize(ctx)

            plugin.ingest(
                {"subject": "api", "predicate": "uses", "object": "https"},
                to_stable=True,
            )
            result = plugin.enrich_prompt("base prompt")
            assert "base prompt" in result
            assert "知识图谱背景" in result

            plugin.shutdown()

    def test_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = KnowledgePlugin()
            plugin.initialize(ctx)

            plugin.ingest(
                {"subject": "db", "predicate": "stores", "object": "data"},
                to_stable=True,
            )
            plugin.shutdown()  # saves

            # Load fresh
            plugin2 = KnowledgePlugin()
            plugin2.initialize(ctx)
            assert plugin2._graph.entity_count >= 1
            plugin2.shutdown()

    def test_persistence_roundtrip_with_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = KnowledgePlugin()
            plugin.initialize(ctx)

            plugin.ingest(
                {"subject": "db", "predicate": "stores", "object": "data"},
                to_stable=True,
            )
            plugin.shutdown()

            # Load fresh
            plugin2 = KnowledgePlugin()
            plugin2.initialize(ctx)
            assert plugin2._graph.entity_count >= 1
            plugin2.shutdown()


class TestKnowledgeReferences:
    """Tests for knowledge reference functions — cross-agent knowledge sharing."""

    def test_add_reference_creates_record(self, tmp_path, monkeypatch):
        """Create a reference and verify it appears in list_references."""
        monkeypatch.setattr(
            "tain_agent.plugins.knowledge.lifecycle._project_root",
            lambda: tmp_path,
        )

        # Set up source agent's knowledge directory and file
        source_knowledge = tmp_path / "agent_workspace" / "sage" / "knowledge"
        source_knowledge.mkdir(parents=True)
        (source_knowledge / "framework_bug_inventory.md").write_text(
            "# Framework Bug Inventory\n\nBugs found in the Tain framework."
        )

        result = add_reference(
            "sage", "framework_bug_inventory.md", "framework_constraints", "puzzle"
        )
        assert result["success"] is True
        assert result["reference_id"] == "sage::framework_bug_inventory.md"
        assert result["record"]["source_agent"] == "sage"
        assert result["record"]["category"] == "framework_constraints"
        assert result["record"]["status"] == "active"

        listed = list_references("puzzle")
        assert listed["success"] is True
        assert listed["count"] == 1
        assert listed["references"][0]["source_agent"] == "sage"
        assert listed["references"][0]["path"] == "framework_bug_inventory.md"

    def test_add_reference_rejects_missing_source(self, tmp_path, monkeypatch):
        """Reference to nonexistent agent/path must fail."""
        monkeypatch.setattr(
            "tain_agent.plugins.knowledge.lifecycle._project_root",
            lambda: tmp_path,
        )

        # Do not create the source file
        result = add_reference(
            "sage", "nonexistent.md", "framework_constraints", "puzzle"
        )
        assert result["success"] is False
        assert "error" in result
        assert "Source file not found" in result["error"]

    def test_sync_references_updates_timestamps(self, tmp_path, monkeypatch):
        """Create a reference then sync; verify synced count."""
        monkeypatch.setattr(
            "tain_agent.plugins.knowledge.lifecycle._project_root",
            lambda: tmp_path,
        )

        source_knowledge = tmp_path / "agent_workspace" / "sage" / "knowledge"
        source_knowledge.mkdir(parents=True)
        (source_knowledge / "framework_bug_inventory.md").write_text("content")

        add_reference(
            "sage", "framework_bug_inventory.md", "framework_constraints", "puzzle"
        )

        # Small delay so the synced timestamp is visibly different
        import time
        time.sleep(0.01)

        result = sync_references("puzzle")
        assert result["success"] is True
        assert result["synced"] == 1
        assert "Synced 1 references" in result["message"]

    def test_get_referenced_files_returns_paths(self, tmp_path, monkeypatch):
        """Create a reference, verify get_referenced_files returns the correct Path."""
        monkeypatch.setattr(
            "tain_agent.plugins.knowledge.lifecycle._project_root",
            lambda: tmp_path,
        )

        source_knowledge = tmp_path / "agent_workspace" / "sage" / "knowledge"
        source_knowledge.mkdir(parents=True)
        (source_knowledge / "framework_bug_inventory.md").write_text("content")

        add_reference(
            "sage", "framework_bug_inventory.md", "framework_constraints", "puzzle"
        )

        files = get_referenced_files("puzzle")
        assert len(files) == 1
        assert files[0].name == "framework_bug_inventory.md"
        assert "sage" in str(files[0])
        assert isinstance(files[0], Path)

    def test_empty_references_graceful(self, tmp_path, monkeypatch):
        """List/sync/get on an agent with no references returns empty/zero results."""
        monkeypatch.setattr(
            "tain_agent.plugins.knowledge.lifecycle._project_root",
            lambda: tmp_path,
        )

        # No references file exists for this agent
        listed = list_references("unknown")
        assert listed["success"] is True
        assert listed["count"] == 0
        assert listed["references"] == []

        synced = sync_references("unknown")
        assert synced["success"] is True
        assert synced["synced"] == 0

        files = get_referenced_files("unknown")
        assert files == []


# ── GoalManager tests ────────────────────────────────────────────────

from tain_agent.plugins.knowledge.goal_manager import GoalManager, Goal


class TestGoalManager:
    """Tests for GoalManager — agent goal tracking with JSON persistence."""

    def test_create_and_list(self):
        """GoalManager.create() adds an active goal, list_active() returns it."""
        gm = GoalManager()
        goal = gm.create("Learn Rust", "Complete the Rust book")
        assert goal.status == "active"
        assert goal.description == "Learn Rust"
        active = gm.list_active()
        assert len(active) == 1
        assert active[0]["id"] == goal.id

    def test_complete(self):
        """GoalManager.complete() marks goal as completed."""
        gm = GoalManager()
        goal = gm.create("Write tests", "95% coverage")
        assert gm.complete(goal.id, "Done")
        assert len(gm.list_active()) == 0
        assert len(gm.list_completed()) == 1
        assert gm.list_completed()[0]["summary"] == "Done"

    def test_persist_and_load(self, tmp_path):
        """GoalManager persists to JSON and reloads."""
        path = tmp_path / "goals.json"
        gm1 = GoalManager()
        gm1.initialize(path)
        gm1.create("Goal A", "Criteria A")

        gm2 = GoalManager()
        gm2.initialize(path)
        assert len(gm2.list_active()) == 1
        assert gm2.list_active()[0]["description"] == "Goal A"
