"""Integration tests — agent lifecycle across create -> run -> stop -> restart.

Tests the full lifecycle of a TaoAgent instance without requiring an actual
LLM backend (backend is None when no API key is set).
"""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace with a minimal config that does not
    require a real LLM backend."""
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        config = ws / "config.yaml"
        config.write_text(f"""
framework: {{version: "0.5.0"}}
agent: {{default_agent: integration_test}}
llm: {{provider: test, model: test, max_tokens: 100, api_key_env: NONE}}
exploration: {{max_exploration_cycles: 10, max_definition_cycles: 5, min_bootstrap_cycles: 3, min_action_categories: 2}}
agent_workspace: {{dir: "{ws}"}}
safety: {{protected_paths: []}}
logging: {{directory: "/tmp", decision_log_file: test.jsonl, memory_file: test.json}}
""")
        yield ws


# ── Agent Lifecycle ──────────────────────────────────────────────────────

class TestAgentLifecycle:
    def test_agent_create_and_stop(self, temp_workspace):
        """Agent initializes with phase='explore' and stop() runs cleanly."""
        from tain_agent.core.agent import TaoAgent

        agent = TaoAgent(
            config_path=str(temp_workspace / "config.yaml"),
            agent_name="test_lifecycle",
        )
        assert agent.agent_name == "test_lifecycle"
        assert agent.phase == "explore"
        agent.stop()

    def test_agent_phase_starts_as_explore(self, temp_workspace):
        """A newly created agent always begins in the explore phase."""
        from tain_agent.core.agent import TaoAgent

        agent = TaoAgent(
            config_path=str(temp_workspace / "config.yaml"),
            agent_name="test_phase",
        )
        assert agent.phase == "explore"

    def test_agent_phase_persists_across_instances(self, temp_workspace):
        """Phase saved to long-term memory survives agent re-creation."""
        from tain_agent.core.agent import TaoAgent

        agent1 = TaoAgent(
            config_path=str(temp_workspace / "config.yaml"),
            agent_name="test_persist",
        )
        agent1.phase = "work"
        agent1._save_phase_to_memory()
        agent1.stop()  # flushes memory to disk

        agent2 = TaoAgent(
            config_path=str(temp_workspace / "config.yaml"),
            agent_name="test_persist",
        )
        assert agent2.phase == "work"

    def test_agent_tool_registry_populated(self, temp_workspace):
        """Primal + evolution tools are registered during init."""
        from tain_agent.core.agent import TaoAgent

        agent = TaoAgent(
            config_path=str(temp_workspace / "config.yaml"),
            agent_name="test_tools",
        )
        tools = agent.tools.list_tools()
        assert len(tools) > 0, "Agent should have primal tools registered"

    def test_agent_no_backend_run_returns_0(self, temp_workspace):
        """When no API key is set, backend is None and run() returns 0."""
        from tain_agent.core.agent import TaoAgent

        agent = TaoAgent(
            config_path=str(temp_workspace / "config.yaml"),
            agent_name="test_no_backend",
        )
        assert agent.backend is None
        result = agent.run()
        assert result == 0


# ── Conversation Persistence ──────────────────────────────────────────────

class TestConversationPersistence:
    def test_conversation_clear_and_append(self, temp_workspace):
        from tain_agent.core.agent import TaoAgent

        agent = TaoAgent(
            config_path=str(temp_workspace / "config.yaml"),
            agent_name="test_conv",
        )
        agent.conversation.clear()
        agent.conversation.append("user", "Hello")
        assert agent.conversation.len() == 1

    def test_conversation_checkpoint_does_not_crash(self, temp_workspace):
        from tain_agent.core.agent import TaoAgent

        agent = TaoAgent(
            config_path=str(temp_workspace / "config.yaml"),
            agent_name="test_checkpoint",
        )
        agent.conversation.append("user", "Hello")
        result = agent.conversation.checkpoint()
        assert result is not None
        assert "message_count" in result


# ── Registry Resilience ───────────────────────────────────────────────────

class TestRegistryResilience:
    def test_list_agents_handles_missing_registry(self, temp_workspace):
        """list_agents returns a dict even when no agents are registered."""
        from tain_agent.core.agent_factory import AgentFactory

        factory = AgentFactory(workspace_root=str(temp_workspace))
        agents = factory.list_agents()
        assert isinstance(agents, dict)

    def test_factory_create_and_list_agents(self, temp_workspace):
        """Creating an agent adds it to the factory registry."""
        from tain_agent.core.agent_factory import AgentFactory

        factory = AgentFactory(workspace_root=str(temp_workspace / "ws"))
        result = factory.create("test_agent", mode="chaos")
        assert "error" not in result
        agents = factory.list_agents()
        assert "test_agent" in agents

    def test_factory_exists_check(self, temp_workspace):
        from tain_agent.core.agent_factory import AgentFactory

        factory = AgentFactory(workspace_root=str(temp_workspace / "ws2"))
        assert factory.exists("nonexistent") is False
        factory.create("real_agent", mode="chaos")
        assert factory.exists("real_agent") is True


# ── Agent State ───────────────────────────────────────────────────────────

class TestAgentState:
    def test_save_state_returns_dict(self, temp_workspace):
        from tain_agent.core.agent import TaoAgent

        agent = TaoAgent(
            config_path=str(temp_workspace / "config.yaml"),
            agent_name="test_state",
        )
        state = agent.save_state()
        assert isinstance(state, dict)
        assert state["agent_name"] == "test_state"
        assert state["phase"] == "explore"

    def test_health_check_returns_dict(self, temp_workspace):
        from tain_agent.core.agent import TaoAgent

        agent = TaoAgent(
            config_path=str(temp_workspace / "config.yaml"),
            agent_name="test_health",
        )
        health = agent.health_check()
        assert isinstance(health, dict)
        assert "status" in health
        assert health["status"] in ("ok", "warning", "critical")
