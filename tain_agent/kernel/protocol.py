"""PluginProtocol, AgentContext, HealthStatus — the contract every plugin fulfills."""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable


@dataclass
class HealthStatus:
    status: Literal["ok", "warning", "critical"] = "ok"
    metrics: dict[str, float] = field(default_factory=dict)
    alerts: list[str] = field(default_factory=list)


@dataclass
class AgentContext:
    agent_name: str
    agent_id: str
    evolution_mode: str              # "specified" | "chaos"
    workspace_path: Path
    config: dict
    kernel_version: str


@runtime_checkable
class PluginProtocol(Protocol):
    """Contract every plugin must satisfy.

    Required: initialize, shutdown, health_check, snapshot, restore.
    Optional: on_cycle_start, on_cycle_end, enrich_prompt, on_llm_response.
    """

    # ── Lifecycle ──
    def initialize(self, ctx: AgentContext) -> None: ...
    def shutdown(self) -> None: ...

    # ── State ──
    def health_check(self) -> HealthStatus: ...
    def snapshot(self) -> dict: ...
    def restore(self, data: dict) -> None: ...

    # ── PRAL hooks (optional) ──
    def on_cycle_start(self, cycle: int) -> None: ...
    def on_cycle_end(self, cycle: int) -> None: ...
    def enrich_prompt(self, base: str) -> str: ...
    def on_llm_response(self, response: Any) -> None: ...
