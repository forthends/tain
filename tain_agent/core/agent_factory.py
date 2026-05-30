"""
Agent Factory — Agent工厂

Manages the lifecycle of all agents in the framework:
- Creation: initialize workspace, register agent, seed personality
- Discovery: list agents, check existence, get agent info
- Registration: maintain _registry.json for inter-agent awareness
- Migration: handle framework version upgrades

This is the entry point for the multi-agent architecture (v0.4.0).
"""

import json
import shutil
from pathlib import Path
from typing import Optional

from tain_agent import __version__
from tain_agent.core.time_utils import now

# ─── Constants ──────────────────────────────────────────────────────────

EVOLUTION_MODE_CHAOS = "chaos"
EVOLUTION_MODE_SPECIFIED = "specified"
EVOLUTION_MODES = (EVOLUTION_MODE_CHAOS, EVOLUTION_MODE_SPECIFIED)

AGENT_NAME_PATTERN = r"^[a-z][a-z0-9_-]{0,31}$"
RESERVED_NAMES = frozenset({"_registry", "_messages", "_system"})

# Subdirectories created inside each agent workspace
from tain_agent.storage_registry import WORKSPACE_DIRS as AGENT_WORKSPACE_SUBDIRS


class AgentFactory:
    """Manages agent creation, discovery, and lifecycle.

    Each agent lives in its own directory under the workspace root:
        agent_workspace/
          _registry.json
          _message_bus.db         # SQLite message bus
          _messages/              # (legacy — kept for backward compat)
          <agent_name>/
            version.json
            personality.json
            state/
            logs/
            ...

    Usage:
        factory = AgentFactory(workspace_root="agent_workspace")
        factory.create("poet", mode="specified",
                       role="诗人", role_description="...")
        agents = factory.list_agents()
    """

    def __init__(self, workspace_root: str = "agent_workspace"):
        self._root = Path(workspace_root).resolve()
        self._registry_path = self._root / "_registry.json"
        self._messages_dir = self._root / "_messages"
        self._ensure_infrastructure()

    # ── Infrastructure ────────────────────────────────────────────────

    def _ensure_infrastructure(self) -> None:
        """Ensure workspace root, registry, and message bus exist."""
        self._root.mkdir(parents=True, exist_ok=True)
        self._messages_dir.mkdir(parents=True, exist_ok=True)
        if not self._registry_path.exists():
            self._write_registry({"registry_version": "1.0", "agents": {}})

    # ── Registry I/O ──────────────────────────────────────────────────

    def _read_registry(self) -> dict:
        """Read the global agent registry."""
        try:
            return json.loads(self._registry_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {"registry_version": "1.0", "agents": {}}

    def _write_registry(self, data: dict) -> None:
        """Write the global agent registry atomically."""
        tmp = self._registry_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self._registry_path)

    # ── Agent CRUD ────────────────────────────────────────────────────

    def exists(self, name: str) -> bool:
        """Check if an agent with the given name exists."""
        return (self._root / name).is_dir()

    def create(self, name: str, mode: str = EVOLUTION_MODE_CHAOS,
               role: str = "", role_description: str = "",
               framework_version: str = __version__) -> dict:
        """Create a new agent workspace and register it.

        Args:
            name: Globally unique agent name (a-z, 0-9, -, _).
            mode: 'chaos' or 'specified'.
            role: Required if mode='specified'. The agent's role (e.g. "诗人").
            role_description: Required if mode='specified'. Role description.
            framework_version: Current framework version.

        Returns:
            dict with agent info, or {"error": ...} on failure.

        Raises:
            ValueError if name is invalid or mode is unknown.
        """
        import re

        # ── Validation ──────────────────────────────────────────────
        if name in RESERVED_NAMES:
            return {"error": f"'{name}' is a reserved name. Choose a different name."}
        if not re.match(AGENT_NAME_PATTERN, name):
            return {"error": (
                f"Invalid agent name '{name}'. Must be 1-32 chars, "
                f"lowercase letters/digits/hyphens/underscores, start with a letter."
            )}
        if mode not in EVOLUTION_MODES:
            return {"error": f"Unknown mode '{mode}'. Use 'chaos' or 'specified'."}
        if mode == EVOLUTION_MODE_SPECIFIED and (not role or not role_description):
            return {"error": "Specified mode requires role and role_description."}
        if self.exists(name):
            return {"error": f"Agent '{name}' already exists."}

        # ── Create workspace ────────────────────────────────────────
        agent_dir = self._root / name
        agent_dir.mkdir(parents=True, exist_ok=True)
        for sub in AGENT_WORKSPACE_SUBDIRS:
            (agent_dir / sub).mkdir(parents=True, exist_ok=True)

        now_ts = now().isoformat()

        # ── Write version.json ──────────────────────────────────────
        version_data = {
            "agent_version": "0.0.1",
            "framework_version": framework_version,
            "evolution_mode": mode,
            "role": role if mode == EVOLUTION_MODE_SPECIFIED else None,
            "role_description": role_description if mode == EVOLUTION_MODE_SPECIFIED else None,
            "initialized_at": now_ts,
            "last_run_at": None,
        }
        (agent_dir / "version.json").write_text(
            json.dumps(version_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # ── Seed personality for specified mode ─────────────────────
        if mode == EVOLUTION_MODE_SPECIFIED:
            self._seed_personality(agent_dir, name, role, role_description)

        # ── Register ────────────────────────────────────────────────
        registry = self._read_registry()
        registry["agents"][name] = {
            "name": name,
            "evolution_mode": mode,
            "role": role if mode == EVOLUTION_MODE_SPECIFIED else None,
            "role_description": role_description if mode == EVOLUTION_MODE_SPECIFIED else None,
            "framework_version": framework_version,
            "created_at": now_ts,
            "last_active_at": now_ts,
            "status": "stopped",
            "pid": None,
        }
        self._write_registry(registry)

        return registry["agents"][name]

    def _seed_personality(self, agent_dir: Path, name: str,
                          role: str, description: str) -> None:
        """Generate initial personality traits from role description via LLM.

        If no LLM is available (e.g. during creation from CLI), writes a
        minimal seed that the agent will expand on first run.
        """
        seed_traits = {
            "values": [],
            "communication_style": [],
            "interests": [],
            "quirks": [],
            "self_description": [
                {
                    "value": f"我是一名{role}",
                    "confidence": 0.7,
                    "emergence_story": f"在诞生时被赋予的角色身份：{description}",
                    "first_observed_at": now().isoformat(),
                    "last_updated_at": now().isoformat(),
                    "observations": 1,
                    "reinforcement_stories": [],
                }
            ],
            "relationship_stance": [],
            "growth_orientation": [
                {
                    "value": description,
                    "confidence": 0.6,
                    "emergence_story": "诞生时的角色使命描述",
                    "first_observed_at": now().isoformat(),
                    "last_updated_at": now().isoformat(),
                    "observations": 1,
                    "reinforcement_stories": [],
                }
            ],
        }

        personality_data = {
            "version": 1,
            "created_at": now().isoformat(),
            "traits": seed_traits,
            "evolution_log": [
                {
                    "action": "seeded",
                    "category": "self_description",
                    "value": f"角色种子: {role}",
                    "story": f"Agent以指定人格模式创建: {description}",
                    "at": now().isoformat(),
                }
            ],
            "saved_at": now().isoformat(),
        }

        state_dir = agent_dir / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "personality.json").write_text(
            json.dumps(personality_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── Discovery ────────────────────────────────────────────────────

    def list_agents(self) -> dict[str, dict]:
        """Return all registered agents. Format: {name: info}."""
        return self._read_registry().get("agents", {})

    def get_agent(self, name: str) -> Optional[dict]:
        """Get info for a specific agent, or None if not found."""
        return self.list_agents().get(name)

    def agent_dir(self, name: str) -> Path:
        """Get the workspace directory path for an agent."""
        return self._root / name

    # ── Status Management ────────────────────────────────────────────

    def update_status(self, name: str, status: str, pid: int = None) -> None:
        """Update an agent's running status and PID in the registry."""
        registry = self._read_registry()
        if name in registry["agents"]:
            registry["agents"][name]["status"] = status
            registry["agents"][name]["pid"] = pid
            registry["agents"][name]["last_active_at"] = now().isoformat()
            self._write_registry(registry)

    def mark_running(self, name: str, pid: int) -> None:
        self.update_status(name, "running", pid)

    def mark_stopped(self, name: str) -> None:
        self.update_status(name, "stopped", None)

    # ── Compatibility ────────────────────────────────────────────────

    def check_compatibility(self, name: str,
                            framework_version: str) -> tuple[bool, str]:
        """Check if an agent is compatible with the given framework version.

        Returns:
            (compatible: bool, message: str)
        """
        agent = self.get_agent(name)
        if not agent:
            return False, f"Agent '{name}' not found."

        agent_fw = agent.get("framework_version", "0.0.0")
        agent_major = int(agent_fw.split(".")[0])
        fw_major = int(framework_version.split(".")[0])

        if agent_major != fw_major:
            return False, (
                f"Agent '{name}' was created with framework v{agent_fw}, "
                f"but current framework is v{framework_version}. "
                f"Major version mismatch — migration required."
            )

        return True, "OK"

    # ── Messages ─────────────────────────────────────────────────────

    @property
    def messages_dir(self) -> Path:
        return self._messages_dir
