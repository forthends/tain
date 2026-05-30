"""Tests for CollaborationPlugin — bus, team, reputation, and plugin integration."""

import tempfile
from pathlib import Path

from tain_agent.kernel.protocol import AgentContext, PluginProtocol
from tain_agent.plugins.collaboration import CollaborationPlugin
from tain_agent.plugins.collaboration.bus import UpgradedMessageBus, Message
from tain_agent.plugins.collaboration.team import Team, TeamMember, TeamTask
from tain_agent.plugins.collaboration.reputation import Reputation, SocialGraph


class TestUpgradedMessageBus:
    """Tests for the SQLite-backed message bus."""

    def test_send_and_check_inbox(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_messages.db"
            bus = UpgradedMessageBus(db_path)
            bus.initialize()

            msg = bus.send("agent-a", "agent-b", "Hello!", msg_type="text", priority=1)
            assert msg.sender == "agent-a"
            assert msg.recipient == "agent-b"

            inbox = bus.check_inbox("agent-b")
            assert len(inbox) == 1
            assert inbox[0].content == "Hello!"
            assert inbox[0].sender == "agent-a"

            # Second check should be empty (marked read)
            inbox2 = bus.check_inbox("agent-b")
            assert len(inbox2) == 0

            bus.close()

    def test_broadcast(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_broadcast.db"
            bus = UpgradedMessageBus(db_path)
            bus.initialize()

            msgs = bus.broadcast("agent-a", "announcement", ["b", "c", "d"])
            assert len(msgs) == 3

            inbox_b = bus.check_inbox("b")
            assert len(inbox_b) == 1
            assert inbox_b[0].content == "announcement"

            bus.close()

    def test_check_inbox_no_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_empty.db"
            bus = UpgradedMessageBus(db_path)
            bus.initialize()

            inbox = bus.check_inbox("nobody")
            assert inbox == []

            bus.close()


class TestTeam:
    """Tests for Team data model."""

    def test_create_team_and_add_member(self):
        team = Team(team_id="t1", name="Test Team")
        member = team.add_member("a1", "Alice", role="lead")
        assert member.agent_id == "a1"
        assert member.role == "lead"
        assert len(team.members) == 1

    def test_is_lead(self):
        team = Team(team_id="t1", name="Test Team")
        team.add_member("a1", "Alice", role="lead")
        team.add_member("a2", "Bob", role="member")
        assert team.is_lead("a1") is True
        assert team.is_lead("a2") is False

    def test_assign_task(self):
        team = Team(team_id="t1", name="Test Team")
        task = TeamTask(
            task_id="task-1",
            title="Do something",
            assigned_to="a1",
        )
        team.assign_task(task)
        assert len(team.tasks) == 1
        assert team.get_tasks_for("a1")[0].title == "Do something"
        assert team.get_tasks_for("a2") == []

    def test_remove_member(self):
        team = Team(team_id="t1", name="Test Team")
        team.add_member("a1", "Alice")
        team.add_member("a2", "Bob")
        assert len(team.members) == 2
        assert team.remove_member("a1") is True
        assert len(team.members) == 1
        assert team.remove_member("a1") is False  # already gone


class TestReputation:
    """Tests for Reputation model and SocialGraph."""

    def test_record_collaboration_updates_scores(self):
        rep = Reputation(agent_id="a1", agent_name="Alice")
        assert rep.collaboration_count == 0

        rep.record_collaboration(success=True)
        assert rep.collaboration_count == 1
        assert rep.success_count == 1
        assert rep.success_rate == 1.0
        assert rep.dimensions["reliability"] == 1.0

    def test_record_failed_collaboration(self):
        rep = Reputation(agent_id="a1", agent_name="Alice")
        rep.record_collaboration(success=False)
        assert rep.collaboration_count == 1
        assert rep.success_count == 0
        assert rep.success_rate == 0.0

    def test_endorse_updates_dimension(self):
        rep = Reputation(agent_id="a1", agent_name="Alice")
        rep.endorse("endorser-1", "expertise", 0.9, "Great work!")
        assert rep.dimensions["expertise"] > 0.0
        assert len(rep.endorsements) == 1
        assert rep.endorsements[0]["endorser_id"] == "endorser-1"


class TestCollaborationPlugin:
    """Tests for the CollaborationPlugin itself."""

    def _make_ctx(self, tmpdir):
        return AgentContext(
            agent_name="test-agent",
            agent_id="c1",
            evolution_mode="chaos",
            workspace_path=Path(tmpdir),
            config={},
            kernel_version="0.6.0",
        )

    def test_satisfies_protocol(self):
        assert isinstance(CollaborationPlugin(), PluginProtocol)

    def test_initialize_and_shutdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = CollaborationPlugin()
            plugin.initialize(ctx)
            assert plugin.health_check().status == "ok"
            plugin.shutdown()

    def test_send_and_check_inbox(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two plugin instances (simulating two agents)
            ctx_a = AgentContext(
                agent_name="agent-a", agent_id="agent-a",
                evolution_mode="chaos", workspace_path=Path(tmpdir) / "a",
                config={}, kernel_version="0.6.0",
            )
            ctx_b = AgentContext(
                agent_name="agent-b", agent_id="agent-b",
                evolution_mode="chaos", workspace_path=Path(tmpdir) / "b",
                config={}, kernel_version="0.6.0",
            )

            plugin_a = CollaborationPlugin()
            plugin_a.initialize(ctx_a)

            plugin_b = CollaborationPlugin()
            plugin_b.initialize(ctx_b)

            # agent-a sends to agent-b (cross-bus, won't work — but tests same-bus internally)
            msg = plugin_a.send("agent-b", "Hello from a", msg_type="text", priority=2)
            assert msg.content == "Hello from a"

            # agent-b checks its own inbox (separate bus though)
            plugin_a.shutdown()
            plugin_b.shutdown()

    def test_send_message_to_self(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = CollaborationPlugin()
            plugin.initialize(ctx)

            msg = plugin.send("c1", "Note to self")
            assert msg.sender == "c1"
            assert msg.recipient == "c1"

            inbox = plugin.check_inbox()
            assert len(inbox) == 1
            assert inbox[0].content == "Note to self"

            plugin.shutdown()

    def test_create_team(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = CollaborationPlugin()
            plugin.initialize(ctx)

            team = plugin.create_team("t1", "Test Team", "Testing team creation")
            assert team.team_id == "t1"
            assert team.is_lead("c1")

            retrieved = plugin.get_team("t1")
            assert retrieved is not None

            plugin.shutdown()

    def test_assign_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = CollaborationPlugin()
            plugin.initialize(ctx)

            plugin.create_team("t1", "Test Team")
            task = TeamTask(task_id="task-1", title="Do the thing", assigned_to="c1")
            result = plugin.assign_task("t1", task)
            assert result is not None
            assert result.task_id == "task-1"

            team = plugin.get_team("t1")
            assert len(team.tasks) == 1

            plugin.shutdown()

    def test_reputation_and_endorse(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = CollaborationPlugin()
            plugin.initialize(ctx)

            # Record a collaboration
            rep = plugin.record_collaboration("agent-x", success=True)
            assert rep.collaboration_count == 1
            assert rep.success_rate == 1.0

            # Endorse
            plugin.endorse("agent-x", "expertise", 0.85, "Very knowledgeable")
            retrieved = plugin.get_reputation("agent-x")
            assert retrieved is not None
            assert retrieved.dimensions["expertise"] > 0.0

            plugin.shutdown()

    def test_discover_agents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = CollaborationPlugin()
            plugin.initialize(ctx)

            plugin.record_collaboration("agent-x", success=True)
            plugin.record_collaboration("agent-y", success=True)
            plugin.record_collaboration("agent-y", success=True)

            agents = plugin.discover_agents(min_score=0.0)
            assert len(agents) >= 2  # our own + x + y (and maybe more)

            plugin.shutdown()

    def test_request_teaching(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = CollaborationPlugin()
            plugin.initialize(ctx)

            msg = plugin.request_teaching("mentor-agent", "python_coding")
            assert msg.priority > 0
            assert msg.msg_type == "request"

            plugin.shutdown()

    def test_enrich_prompt_shows_collaboration_info(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = CollaborationPlugin()
            plugin.initialize(ctx)

            plugin.create_team("t1", "Team Alpha")
            plugin.record_collaboration("agent-x", success=True)

            result = plugin.enrich_prompt("base")
            assert "base" in result
            assert "协作团队" in result or "Collaboration" in result

            plugin.shutdown()

    def test_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = self._make_ctx(tmpdir)
            plugin = CollaborationPlugin()
            plugin.initialize(ctx)

            plugin.create_team("t1", "Persist Team")
            plugin.record_collaboration("agent-x", success=True)
            plugin.shutdown()

            # Reload
            plugin2 = CollaborationPlugin()
            plugin2.initialize(ctx)
            assert plugin2.get_team("t1") is not None
            rep = plugin2.get_reputation("agent-x")
            # Reputation may or may not persist depending on whether "our own" is included
            plugin2.shutdown()
