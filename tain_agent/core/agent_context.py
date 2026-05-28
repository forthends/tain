"""
AgentContext — unified container for all agent subsystems.

Replaces the mixin pattern with a single @dataclass that holds every
subsystem instance. All agent operations take a context and operate
on it, rather than spreading state across 5 mixin classes.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any


@dataclass
class AgentContext:
    """All subsystems and configuration for a single agent instance.

    This replaces the AgentSubsystemsMixin, AgentConfigMixin,
    AgentCognitionMixin, AgentPhaseMixin, and AgentToolsMixin.
    """

    # ── Identity ──────────────────────────────────────────────────────
    agent_name: str = ""
    framework_version: str = "0.5.0"
    evolution_mode: str = "chaos"
    role: str = ""
    role_description: str = ""

    # ── Phase & lifecycle ─────────────────────────────────────────────
    phase: str = "explore"
    cycle_count: int = 0
    _running: bool = False
    _rate_limit_exit_code: int = 0

    # ── Configuration ─────────────────────────────────────────────────
    config: dict = field(default_factory=dict)
    config_path: str = "config.yaml"
    protected_paths: set = field(default_factory=set)

    # ── Paths ─────────────────────────────────────────────────────────
    _workspace_path: Optional[Path] = None

    # ── Subsystems (set after init) ───────────────────────────────────
    memory: Any = None
    decision_log: Any = None
    conversation: Any = None
    tools: Any = None
    forge: Any = None
    goals: Any = None
    self_modify: Any = None
    lineage: Any = None
    capability: Any = None
    reporter: Any = None
    pipeline: Any = None
    improvement_loop: Any = None
    cognitive_loop: Any = None
    personality: Any = None
    drive_system: Any = None
    backend: Any = None
    llm_logger: Any = None
    diversity: dict = field(default_factory=dict)
    drives: dict = field(default_factory=dict)

    # ── Bootstrap tracking ────────────────────────────────────────────
    _bootstrap_action_categories: set = field(default_factory=set)
    _readonly_streak: int = 0

    @property
    def factory(self):
        """Lazy-load the agent factory for registry operations."""
        from tain_agent.core.agent_factory import AgentFactory
        return AgentFactory()
