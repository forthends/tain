"""Protocol definitions for Mixin interface contracts.

These define the expected attributes/methods each Mixin provides or consumes,
making the implicit hasattr() contracts explicit and type-checkable.

Note: @runtime_checkable Protocols with non-method members do not support
issubclass() in Python 3.12+. Use isinstance(obj, Protocol) for runtime
checks; issubclass() works for static type checkers (mypy, pyright) on
non-runtime-checkable Protocols.
"""
from typing import Protocol, runtime_checkable


@runtime_checkable
class ConfigProvider(Protocol):
    """Provided by AgentConfigMixin."""
    config: dict
    agent_name: str
    workspace_root: str
    framework_version: str
    model: str
    max_tokens: int
    api_key: str
    protected_paths: list[str]
    confirm_destructive: bool
    log_dir: str
    decision_log_file: str
    memory_file: str
    max_exploration_cycles: int
    max_definition_cycles: int
    min_action_categories: int
    evolution_mode: str
    role: str
    role_description: str

    def _load_config(self, config_path: str) -> None: ...
    def _load_agent_identity(self) -> None: ...
    def _load_phase_from_memory(self) -> str: ...
    def _save_phase_to_memory(self) -> None: ...


@runtime_checkable
class PhaseProvider(Protocol):
    """Provided by AgentPhaseMixin."""
    phase: str
    cycle_count: int
    PHASES: tuple
    MAX_CYCLES: dict
    _bootstrap_action_categories: set
    _TOOL_CATEGORY_MAP: dict[str, str]

    def _build_initial_message(self) -> str: ...
    def _track_action_category(self, tool_name: str) -> None: ...
    def _advance_phase(self) -> None: ...
