"""Tests for IdentityPlugin and AgentIdentity model."""

import pytest
from pathlib import Path
from tain_agent.kernel.protocol import AgentContext, PluginProtocol
from tain_agent.plugins.identity import IdentityPlugin
from tain_agent.plugins.identity.model import (
    AgentIdentity, DomainExpertise, Proficiency, Value, Goal,
    BehaviorConstraints, AutonomyLevel, CollaborationPrefs,
)


@pytest.fixture
def agent_context(tmp_path):
    workspace = tmp_path / "agent_workspace" / "test"
    workspace.mkdir(parents=True)
    return AgentContext("test", "a1", "specified", workspace, {}, "0.6.0")


@pytest.fixture
def identity_plugin():
    return IdentityPlugin()


class TestAgentIdentity:
    def test_specified_mode_awakens_from_role(self):
        identity = AgentIdentity(agent_id="a1", name="test", evolution_mode="specified")
        identity.awaken_from_role("Python 后端工程师", "擅长 FastAPI 和 PostgreSQL")
        assert identity.role == "Python 后端工程师"
        assert len(identity.expertise_domains) == 1
        assert identity.expertise_domains[0].proficiency == Proficiency.BEGINNER
        assert len(identity.values) == 1
        assert identity.values[0].name == "专业精神"

    def test_chaos_mode_starts_empty(self):
        identity = AgentIdentity(agent_id="a1", name="test", evolution_mode="chaos")
        assert identity.role == ""
        assert len(identity.expertise_domains) == 0

    def test_upgrade_autonomy_logs_event(self):
        identity = AgentIdentity(agent_id="a1", name="test")
        identity.upgrade_autonomy(AutonomyLevel.TRUSTED, "verified safe")
        assert identity.constraints.max_autonomy_level == AutonomyLevel.TRUSTED
        assert len(identity.evolution_log) == 1
        assert identity.evolution_log[0].event_type == "autonomy_upgrade"

    def test_goal_tree(self):
        identity = AgentIdentity(agent_id="a1", name="test")
        parent = Goal(id="g1", title="learn Python")
        child = Goal(id="g2", title="learn asyncio")
        parent.add_child(child)
        identity.goals.append(parent)
        assert identity.goals[0].children[0].id == "g2"
        assert identity.goals[0].children[0].parent_id == "g1"


class TestIdentityPlugin:
    def _make_ctx(self):
        return AgentContext(
            agent_name="test", agent_id="a1", evolution_mode="chaos",
            workspace_path=Path("/tmp/test_identity_ws"),
            config={}, kernel_version="0.6.0",
        )

    def test_satisfies_protocol(self):
        assert isinstance(IdentityPlugin(), PluginProtocol)

    def test_initialize_creates_identity(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = AgentContext("test", "a1", "chaos", Path(tmpdir), {}, "0.6.0")
            plugin = IdentityPlugin()
            plugin.initialize(ctx)
            assert plugin.identity is not None
            assert plugin.identity.agent_id == "a1"

    def test_enrich_prompt_adds_context(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            ctx = AgentContext("test", "a1", "chaos", Path(tmpdir), {}, "0.6.0")
            plugin = IdentityPlugin()
            plugin.initialize(ctx)
            result = plugin.enrich_prompt("base prompt")
            assert "base prompt" in result
            assert "## 你的身份" in result


def test_personality_get_context_for_prompt(identity_plugin, agent_context):
    """IdentityPlugin.personality.get_context_for_prompt() returns trait context."""
    identity_plugin.initialize(agent_context)
    ctx = identity_plugin.personality.get_context_for_prompt()
    assert isinstance(ctx, str)


def test_personality_introspect(identity_plugin, agent_context):
    """IdentityPlugin.personality.introspect() returns trait summary."""
    identity_plugin.initialize(agent_context)
    result = identity_plugin.personality.introspect()
    assert isinstance(result, dict)
    assert "traits" in result
