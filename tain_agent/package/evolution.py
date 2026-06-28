"""Package-level evolution — Mutation types and the 5-stage evolve() loop."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Any

from tain_agent.package import LayerKind


@dataclass
class Mutation:
    """An atomic mutation to one layer of a package.

    This is the unit of evolution — one change that modifies files, updates
    the manifest, and bumps the package version.
    """
    layer: LayerKind
    change_type: str
    # "new_tool" | "skill_upgrade" | "artifact" | "knowledge_entry"
    # | "identity_change" | "infra_change"
    detail: str
    files_to_write: list[tuple[str, bytes]]  # [(relative_path, content_bytes)]
    manifest_patch: dict
    source_gap: str = ""


@dataclass
class EvolutionResult:
    """Outcome of one evolution cycle (5-stage loop)."""
    success: bool
    version_from: str
    version_to: str | None = None
    mutation: Mutation | None = None
    stage_failed: str | None = None
    errors: list[str] = field(default_factory=list)

    @classmethod
    def no_gap(cls, version: str) -> "EvolutionResult":
        return cls(success=False, version_from=version,
                   stage_failed="detect_gap",
                   errors=["No gap detected"])

    @classmethod
    def contract_failed(cls, version: str, mutation: Mutation,
                        errors: list[str]) -> "EvolutionResult":
        return cls(success=False, version_from=version,
                   mutation=mutation, stage_failed="contract_check",
                   errors=errors)

    @classmethod
    def write_failed(cls, version: str, mutation: Mutation,
                     errors: list[str]) -> "EvolutionResult":
        return cls(success=False, version_from=version,
                   mutation=mutation, stage_failed="write_package",
                   errors=errors)

    @classmethod
    def rolled_back(cls, mutation: Mutation, errors: list[str]) -> "EvolutionResult":
        return cls(success=False, version_from="", version_to=None,
                   mutation=mutation, stage_failed="online_verify",
                   errors=errors)

    @classmethod
    def success_result(cls, version_from: str, version_to: str,
                       mutation: Mutation) -> "EvolutionResult":
        return cls(success=True, version_from=version_from,
                   version_to=version_to, mutation=mutation)
