"""Backward compatibility — new AgentKernel behind old TaoAgent interface.

Remove this module in v0.7.0 once all consumers (CLI, WebUI) are migrated.
"""

from __future__ import annotations
import logging
import yaml
from pathlib import Path
from tain_agent.kernel import AgentKernel, AgentContext
from tain_agent.plugins.identity import IdentityPlugin
from tain_agent.plugins.memory import MemoryPlugin
from tain_agent.plugins.tool import ToolPlugin
from tain_agent.plugins.skill import SkillPlugin
from tain_agent.plugins.knowledge import KnowledgePlugin
from tain_agent.plugins.workflow import WorkflowPlugin
from tain_agent.plugins.collaboration import CollaborationPlugin

logger = logging.getLogger(__name__)

_FACTORIES = {
    "identity": IdentityPlugin,
    "memory": MemoryPlugin,
    "tool": ToolPlugin,
    "skill": SkillPlugin,
    "knowledge": KnowledgePlugin,
    "workflow": WorkflowPlugin,
    "collaboration": CollaborationPlugin,
}


class TaoAgentCompat:
    """Drop-in replacement for the old TaoAgent class using new Kernel."""

    def __init__(self, config_path: str = "config.yaml", agent_name: str = None):
        with open(config_path) as f:
            config = yaml.safe_load(f)

        name = agent_name or config.get("agent", {}).get("name", "default")
        evolution_mode = config.get("agent", {}).get("evolution_mode", "specified")
        workspace = Path("agent_workspace") / name

        self.agent_name = name
        self.framework_version = "0.6.0"
        self.phase = "explore"
        self.cycle_count = 0

        ctx = AgentContext(
            agent_name=name,
            agent_id=f"{name}-{workspace.name}",
            evolution_mode=evolution_mode,
            workspace_path=workspace,
            config=config,
            kernel_version="0.6.0",
        )
        self.kernel = AgentKernel(ctx)
        self.kernel.load_plugins(_FACTORIES)
        logger.info("TaoAgentCompat initialized for '%s' (mode=%s)", name, evolution_mode)

    def run(self, autonomous: bool = False) -> int:
        """Run agent using new Kernel. Returns exit code."""
        # Wire up existing LLM backend
        from tain_agent.core.llm import LLMBackend
        backend_config = self.kernel.ctx.config.get("llm", {})
        backend = LLMBackend(backend_config)

        from tain_agent.core.conversation import ConversationManager
        conversation = ConversationManager(
            workspace=str(self.kernel.ctx.workspace_path),
            agent_name=self.kernel.ctx.agent_name,
        )

        from tain_agent.core.drives import DriveSystem
        drives = DriveSystem()

        from tain_agent.core.bootstrap import EVOLVE_SYSTEM_PROMPT
        system_prompt = EVOLVE_SYSTEM_PROMPT.format(
            agent_name=self.kernel.ctx.agent_name,
            role=self.kernel.ctx.config.get("identity", {}).get("role", ""),
            role_description=self.kernel.ctx.config.get("identity", {}).get("role_description", ""),
        )

        return self.kernel.run(backend, conversation, drives, system_prompt)

    def stop(self) -> None:
        print(f"\nAgent '{self.agent_name}' stopping...")
        self.kernel.shutdown()

    def health_check(self) -> dict:
        return {
            name: health.__dict__ if hasattr(health, '__dict__') else str(health)
            for name, health in self.kernel.lifecycle.all_health_checks().items()
        }

    @property
    def version(self) -> str:
        return self.framework_version
