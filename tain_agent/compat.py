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
from tain_agent import __version__ as _fw_version

logger = logging.getLogger(__name__)


class _DecisionLogShim:
    """Minimal shim so agent.decision_log.read_all() doesn't crash."""
    def __init__(self, entries: list[dict]):
        self._entries = entries

    def read_all(self) -> list[dict]:
        return list(self._entries)

    def filter_by_phase(self, phase: str) -> list[dict]:
        return [e for e in self._entries if e.get("phase") == phase]


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
        self.framework_version = _fw_version
        self.phase = "explore"
        self.cycle_count = 0

        ctx = AgentContext(
            agent_name=name,
            agent_id=f"{name}-{workspace.name}",
            evolution_mode=evolution_mode,
            workspace_path=workspace,
            config=config,
            kernel_version=_fw_version,
        )
        self.kernel = AgentKernel(ctx)
        self.kernel.load_plugins(_FACTORIES)
        self._backend = None
        self._conversation = None
        self._drives = None
        self._config = config
        self._decision_log_entries: list[dict] = []
        logger.info("TaoAgentCompat initialized for '%s' (mode=%s)", name, evolution_mode)

    def run(self, autonomous: bool = False) -> int:
        """Run agent using new Kernel. Returns exit code."""
        # Wire up existing LLM backend
        from tain_agent.core.llm import LLMBackend
        backend_config = self.kernel.ctx.config.get("llm", {})
        backend = LLMBackend(backend_config)
        self._backend = backend

        from tain_agent.core.conversation import ConversationManager
        conversation = ConversationManager(
            workspace=str(self.kernel.ctx.workspace_path),
            agent_name=self.kernel.ctx.agent_name,
        )
        self._conversation = conversation

        from tain_agent.core.drives import DriveSystem
        drives = DriveSystem()
        self._drives = drives

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

    # ── Legacy attribute proxies for main.py / DialogueBridge ──────

    @property
    def backend(self):
        return self._backend

    @property
    def config(self):
        return self._config

    @property
    def conversation(self):
        return self._conversation

    @property
    def tools(self):
        return None  # new kernel uses plugin dispatch

    @property
    def memory(self):
        return None  # new kernel uses MemoryPlugin

    @property
    def forge(self):
        return None  # tool forge not ported to new kernel yet

    @property
    def goals(self):
        return None  # goal system not ported to new kernel yet

    @property
    def decision_log(self):
        return _DecisionLogShim(self._decision_log_entries)

    def print_state(self) -> None:
        """Print agent state in a format compatible with old TaoAgent."""
        print(f"\n  Agent: {self.agent_name}")
        print(f"  Version: {self.framework_version}")
        print(f"  Phase: {self.phase}")
        print(f"  Cycle: {self.cycle_count}")
        print()
        for name, health in self.kernel.lifecycle.all_health_checks().items():
            status = getattr(health, 'status', str(health))
            print(f"  [{name}] {status}")
        print()

    def health_check(self) -> dict:
        return {
            name: health.__dict__ if hasattr(health, '__dict__') else str(health)
            for name, health in self.kernel.lifecycle.all_health_checks().items()
        }

    @property
    def version(self) -> str:
        return self.framework_version
