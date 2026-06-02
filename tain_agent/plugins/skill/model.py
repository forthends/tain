"""Skill data model — agent skills with maturity tracking."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MaturityLevel(IntEnum):
    NOVICE = 1
    APPRENTICE = 2
    COMPETENT = 3
    PROFICIENT = 4
    EXPERT = 5
    MASTER = 6


MATURITY_THRESHOLDS: dict[MaturityLevel, int] = {
    MaturityLevel.NOVICE: 0,
    MaturityLevel.APPRENTICE: 5,
    MaturityLevel.COMPETENT: 20,
    MaturityLevel.PROFICIENT: 50,
    MaturityLevel.EXPERT: 100,
    MaturityLevel.MASTER: 200,
}


@dataclass
class Step:
    """A single step in a skill workflow."""

    name: str
    description: str = ""
    tool: str = ""             # tool name to invoke
    expected_output: str = ""  # description of expected result
    order: int = 0


@dataclass
class Skill:
    """A skill the agent can learn and improve through practice."""

    name: str
    display_name: str
    description: str = ""
    category: str = "general"
    tools: list[str] = field(default_factory=list)
    knowledge_refs: list[str] = field(default_factory=list)
    workflow: list[Step] = field(default_factory=list)
    maturity: MaturityLevel = MaturityLevel.NOVICE
    usage_count: int = 0
    success_count: int = 0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @property
    def success_rate(self) -> float:
        """Return success rate (0.0-1.0). Returns 0.0 if never used."""
        if self.usage_count == 0:
            return 0.0
        return self.success_count / self.usage_count

    def record_use(self, success: bool = True) -> None:
        """Record a usage event and update maturity."""
        self.usage_count += 1
        if success:
            self.success_count += 1
        self.updated_at = _now()
        self._recalc_maturity()

    def _recalc_maturity(self) -> None:
        """Recompute maturity based on successful use count and success rate."""
        effective = self.success_count
        # Penalty: if success rate drops below 50%, effective count is halved
        if self.usage_count > 0 and self.success_rate < 0.5:
            effective = max(0, int(self.success_count * 0.5))

        new_level = MaturityLevel.NOVICE
        for level in MaturityLevel:
            if effective >= MATURITY_THRESHOLDS[level]:
                new_level = level
        self.maturity = new_level

    def to_dict(self) -> dict[str, Any]:
        import dataclasses
        d = dataclasses.asdict(self)
        d["maturity"] = self.maturity.value
        d["maturity_name"] = self.maturity.name
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Skill":
        data = dict(data)
        # Convert maturity back to enum
        mat_val = data.pop("maturity", 1)
        data.pop("maturity_name", None)
        # Handle workflow steps
        workflow_data = data.pop("workflow", [])
        skill = cls(**data)
        skill.maturity = MaturityLevel(mat_val)
        skill.workflow = [Step(**s) for s in workflow_data]
        return skill
