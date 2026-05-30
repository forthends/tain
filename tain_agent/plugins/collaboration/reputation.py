"""Reputation and social graph — track agent credibility and relationships."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Reputation:
    """Reputation profile for an agent in the social graph."""

    agent_id: str
    agent_name: str
    overall_score: float = 0.0       # -1.0 to 1.0
    dimensions: dict[str, float] = field(default_factory=lambda: {
        "reliability": 0.0,
        "expertise": 0.0,
        "cooperation": 0.0,
        "communication": 0.0,
    })
    endorsements: list[dict[str, Any]] = field(default_factory=list)
    collaboration_count: int = 0
    success_count: int = 0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    @property
    def success_rate(self) -> float:
        if self.collaboration_count == 0:
            return 0.0
        return self.success_count / self.collaboration_count

    def record_collaboration(self, success: bool = True) -> None:
        """Record a collaboration event and update scores."""
        self.collaboration_count += 1
        if success:
            self.success_count += 1

        # Update reliability dimension based on success rate
        self.dimensions["reliability"] = self.success_rate

        # Update cooperation dimension
        cooperation_delta = 0.05 if success else -0.02
        self.dimensions["cooperation"] = max(
            -1.0, min(1.0, self.dimensions["cooperation"] + cooperation_delta)
        )

        self._recalc_overall()
        self.updated_at = _now()

    def endorse(
        self,
        endorser_id: str,
        dimension: str,
        score: float,
        comment: str = "",
    ) -> None:
        """Record an endorsement from another agent."""
        self.endorsements.append({
            "endorser_id": endorser_id,
            "dimension": dimension,
            "score": max(-1.0, min(1.0, score)),
            "comment": comment,
            "timestamp": _now(),
        })

        # Blend endorsements into dimension score
        if dimension in self.dimensions:
            current = self.dimensions[dimension]
            # Weighted average: 70% existing, 30% new endorsement
            self.dimensions[dimension] = current * 0.7 + score * 0.3

        self._recalc_overall()
        self.updated_at = _now()

    def _recalc_overall(self) -> None:
        """Recompute overall score as average of dimensions."""
        if not self.dimensions:
            self.overall_score = 0.0
        else:
            self.overall_score = sum(self.dimensions.values()) / len(self.dimensions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "overall_score": self.overall_score,
            "dimensions": dict(self.dimensions),
            "endorsements": list(self.endorsements),
            "collaboration_count": self.collaboration_count,
            "success_count": self.success_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Reputation":
        data = dict(data)
        return cls(**data)


class SocialGraph:
    """Tracks relationships and reputations across agents."""

    def __init__(self):
        self._reputations: dict[str, Reputation] = {}
        # relationships: agent_id -> set of related agent_ids
        self._relationships: dict[str, set[str]] = {}

    def set_relationship(self, agent_a: str, agent_b: str) -> None:
        """Create or acknowledge a relationship between two agents."""
        if agent_a not in self._relationships:
            self._relationships[agent_a] = set()
        if agent_b not in self._relationships:
            self._relationships[agent_b] = set()
        self._relationships[agent_a].add(agent_b)
        self._relationships[agent_b].add(agent_a)

    def get_collaborators(self, agent_id: str) -> list[str]:
        """Get the list of known collaborators for an agent."""
        return sorted(self._relationships.get(agent_id, set()))

    def get_reputation(self, agent_id: str) -> Reputation | None:
        """Get an agent's reputation profile."""
        return self._reputations.get(agent_id)

    def get_or_create_reputation(
        self, agent_id: str, agent_name: str = ""
    ) -> Reputation:
        """Get or create a reputation profile for an agent."""
        if agent_id not in self._reputations:
            self._reputations[agent_id] = Reputation(
                agent_id=agent_id,
                agent_name=agent_name or agent_id,
            )
        return self._reputations[agent_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reputations": {
                aid: r.to_dict() for aid, r in self._reputations.items()
            },
            "relationships": {
                aid: sorted(rels) for aid, rels in self._relationships.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SocialGraph":
        sg = cls()
        for aid, rdata in data.get("reputations", {}).items():
            sg._reputations[aid] = Reputation.from_dict(rdata)
        for aid, rels in data.get("relationships", {}).items():
            sg._relationships[aid] = set(rels)
        return sg
