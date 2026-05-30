# DEPRECATED since v0.6.0 — logic migrated to tain_agent/kernel/ and tain_agent/plugins/
"""
AgentConfigMixin — configuration loading, identity, and phase persistence.
"""
import json
import os
from pathlib import Path

import yaml

from tain_agent import __version__
from tain_agent.core.time_utils import set_timezone
from tain_agent.core.agent_factory import AgentFactory


class AgentConfigMixin:
    """Mixin for loading agent configuration, identity, and phase state."""

    def _load_phase_from_memory(self) -> str:
        """Load persisted phase from long-term memory, or default to bootstrap."""
        if hasattr(self, 'memory') and self.memory:
            saved = self.memory.long_term.get("agent_phase")
            if saved and saved in self.PHASES:
                return saved
        return "explore"

    def _save_phase_to_memory(self) -> None:
        """Persist current phase to long-term memory."""
        if hasattr(self, 'memory') and self.memory:
            self.memory.long_term.set("agent_phase", self.phase)

    def _load_config(self, config_path: str) -> None:
        """Load configuration from YAML file."""
        self._config_path = config_path
        config_file = Path(config_path)
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f) or {}
        else:
            self.config = {}

        agent_cfg = self.config.get("agent", {})
        llm_cfg = self.config.get("llm", {})
        safety_cfg = self.config.get("safety", {})
        log_cfg = self.config.get("logging", {})

        # Agent name: CLI arg > config default > "default"
        if self.agent_name is None:
            self.agent_name = agent_cfg.get("default_agent", "default")
        self.agent_name = str(self.agent_name)

        self.timezone_name = agent_cfg.get("timezone", "Asia/Shanghai")
        set_timezone(self.timezone_name)
        self.model = llm_cfg.get("model", "MiniMax-M2.7")
        self.max_tokens = llm_cfg.get("max_tokens", 8192)
        self.api_key = os.environ.get(llm_cfg.get("api_key_env", "MINIMAX_API_KEY"), "")
        self.protected_paths = safety_cfg.get("protected_paths", [])
        self.confirm_destructive = safety_cfg.get("confirm_destructive", True)

        # ── Agent Workspace Isolation ───────────────────────────────
        ws_cfg = self.config.get("agent_workspace", {})
        self.workspace_root = ws_cfg.get("dir", "agent_workspace")
        self._workspace_path = (Path(self.workspace_root) / self.agent_name).resolve()

        # All runtime state lives inside the agent's workspace
        self.log_dir = str(self._workspace_path / "logs")
        self.decision_log_file = log_cfg.get("decision_log_file", "decisions.jsonl")
        self.memory_file = log_cfg.get("memory_file", "memory.json")

        self.max_exploration_cycles = self.config.get("exploration", {}).get("max_exploration_cycles", 10)
        self.max_definition_cycles = self.config.get("exploration", {}).get("max_definition_cycles", 5)
        self.min_action_categories = self.config.get("exploration", {}).get("min_action_categories", 2)

        # Framework version & AgentFactory for registry access
        fw_cfg = self.config.get("framework", {})
        self.framework_version = fw_cfg.get("version", __version__)
        self._factory = AgentFactory(workspace_root=self.workspace_root)

        # ── Evolution mode & role ──────────────────────────────────
        self.evolution_mode = "chaos"
        self.role = ""
        self.role_description = ""
        self._workspace_version_path = self._workspace_path / "version.json"
        self._load_agent_identity()

        # Validate config schema (non-fatal if pydantic not installed)
        try:
            from tain_agent.core.config_schema import AppConfig
            AppConfig(**self.config)
        except ImportError:
            pass
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Config validation warning: %s", e)

    def _load_agent_identity(self) -> None:
        """Load evolution mode and role from the agent's version.json, if it exists."""
        if self._workspace_version_path.exists():
            try:
                vdata = json.loads(self._workspace_version_path.read_text(encoding="utf-8"))
                self.evolution_mode = vdata.get("evolution_mode", "chaos")
                self.role = vdata.get("role", "")
                self.role_description = vdata.get("role_description", "")
            except (json.JSONDecodeError, IOError):
                pass
