"""CollaborationPlugin — multi-agent messaging, teams, and reputation.

Three-layer design:
  - Messages:  SQLite-backed message bus (send, check_inbox)
  - Teams:     Team creation and task assignment
  - Society:   Reputation tracking and social graph
"""

from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol
from tain_agent.plugins.collaboration.bus import UpgradedMessageBus, Message
from tain_agent.plugins.collaboration.team import Team, TeamMember, TeamTask
from tain_agent.plugins.collaboration.reputation import Reputation, SocialGraph

logger = logging.getLogger(__name__)


class CollaborationPlugin:
    """Plugin that enables multi-agent collaboration.

    Three layers:
      - messages:  Send and receive typed, prioritized messages via SQLite bus.
      - teams:     Create teams, assign tasks, manage members.
      - society:   Reputation tracking, endorsements, social graph.

    Required PluginProtocol methods: initialize, shutdown, health_check,
    snapshot, restore.
    Optional PRAL hooks: on_cycle_start, on_cycle_end, enrich_prompt,
    on_llm_response.
    """

    version = "1.0.0"

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._bus: UpgradedMessageBus | None = None
        self._teams: dict[str, Team] = {}
        self._social: SocialGraph = SocialGraph()
        self._persist_dir: Path | None = None

    # ── PluginProtocol ──────────────────────────────────────────────

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        self._persist_dir = ctx.workspace_path / "_runtime" / "collaboration"
        self._persist_dir.mkdir(parents=True, exist_ok=True)

        bus_path = self._persist_dir / "messages.db"
        self._bus = UpgradedMessageBus(bus_path)
        self._bus.initialize()

        self._load()

    def shutdown(self) -> None:
        if self._bus:
            self._bus.purge()
            self._bus.close()
            self._bus = None
        self._save()
        self._teams.clear()
        self._social = SocialGraph()
        self._ctx = None

    def health_check(self) -> HealthStatus:
        if self._ctx is None:
            return HealthStatus(status="critical", alerts=["not initialized"])
        if self._bus is None:
            return HealthStatus(status="critical", alerts=["message bus not initialized"])
        metrics = {
            "team_count": float(len(self._teams)),
            "reputation_count": float(len(self._social._reputations)),
            "relationship_count": float(
                sum(len(rels) for rels in self._social._relationships.values())
            ),
        }
        return HealthStatus(status="ok", metrics=metrics)

    def snapshot(self) -> dict[str, Any]:
        return {
            "teams": {tid: t.to_dict() for tid, t in self._teams.items()},
            "social": self._social.to_dict(),
        }

    def restore(self, data: dict[str, Any]) -> None:
        if "teams" in data:
            self._teams = {
                tid: Team.from_dict(tdata)
                for tid, tdata in data["teams"].items()
            }
        if "social" in data:
            self._social = SocialGraph.from_dict(data["social"])

    # ── PRAL hooks ──────────────────────────────────────────────────

    def on_cycle_start(self, cycle: int) -> None:
        pass

    def on_cycle_end(self, cycle: int) -> None:
        self._save()

    def enrich_prompt(self, base: str) -> str:
        parts = [base]

        # Show active teams
        if self._teams:
            parts.append("")
            parts.append("## 协作团队 (Collaboration Teams)")
            for tid, team in sorted(self._teams.items()):
                member_names = [m.agent_name for m in team.members]
                parts.append(f"- **{team.name}** ({tid}): {', '.join(member_names)}")

        # Show reputation summary
        if self._social._reputations:
            parts.append("")
            parts.append("## 社会信誉 (Social Reputation)")
            for aid, rep in self._social._reputations.items():
                parts.append(f"- {rep.agent_name}: {rep.overall_score:+.2f}")

        return "\n".join(parts)

    def on_llm_response(self, response: Any) -> None:
        pass

    # ── Persistence ─────────────────────────────────────────────────

    def _save(self) -> None:
        if self._persist_dir is None:
            return
        try:
            state = {
                "teams": {tid: t.to_dict() for tid, t in self._teams.items()},
                "social": self._social.to_dict(),
            }
            path = self._persist_dir / "state.json"
            path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save collaboration state: %s", e)

    def _load(self) -> None:
        if self._persist_dir is None:
            return
        path = self._persist_dir / "state.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if "teams" in data:
                self._teams = {
                    tid: Team.from_dict(tdata)
                    for tid, tdata in data["teams"].items()
                }
            if "social" in data:
                self._social = SocialGraph.from_dict(data["social"])
        except Exception as e:
            logger.warning("Failed to load collaboration state: %s", e)

    # ── Message Layer ───────────────────────────────────────────────

    def send(
        self,
        to_agent: str,
        content: str,
        msg_type: str = "text",
        priority: int = 0,
        ttl: float = 3600.0,
    ) -> Message:
        """Send a message to another agent."""
        if self._bus is None:
            raise RuntimeError("MessageBus not initialized")
        sender = self._ctx.agent_id if self._ctx else "unknown"
        return self._bus.send(sender, to_agent, content, msg_type, priority, ttl)

    def check_inbox(self, mark_read: bool = True) -> list[Message]:
        """Check for incoming messages addressed to this agent."""
        if self._bus is None:
            return []
        agent_name = self._ctx.agent_id if self._ctx else ""
        return self._bus.check_inbox(agent_name, mark_read=mark_read)

    # ── Team Layer ──────────────────────────────────────────────────

    def create_team(
        self,
        team_id: str,
        name: str,
        description: str = "",
    ) -> Team:
        """Create a new team. The creating agent is the lead."""
        team = Team(team_id=team_id, name=name, description=description)
        if self._ctx:
            team.add_member(self._ctx.agent_id, self._ctx.agent_name, role="lead")
        self._teams[team_id] = team
        return team

    def get_team(self, team_id: str) -> Team | None:
        """Get a team by ID."""
        return self._teams.get(team_id)

    def assign_task(
        self,
        team_id: str,
        task: TeamTask,
    ) -> TeamTask | None:
        """Assign a task to a team. Returns the task or None if team not found."""
        team = self._teams.get(team_id)
        if team is None:
            return None
        team.assign_task(task)
        return task

    # ── Society Layer ───────────────────────────────────────────────

    def get_reputation(self, agent_id: str) -> Reputation | None:
        """Get an agent's reputation profile."""
        return self._social.get_reputation(agent_id)

    def endorse(
        self,
        target_agent_id: str,
        dimension: str,
        score: float,
        comment: str = "",
    ) -> Reputation | None:
        """Endorse another agent in a given dimension.

        Creates the reputation profile if it doesn't exist.
        Returns the updated Reputation or None if self-endorsement.
        """
        if self._ctx and target_agent_id == self._ctx.agent_id:
            return None  # Cannot endorse self

        rep = self._social.get_or_create_reputation(target_agent_id)
        endorser = self._ctx.agent_id if self._ctx else "unknown"
        rep.endorse(endorser, dimension, score, comment)
        return rep

    def record_collaboration(
        self, partner_agent_id: str, success: bool = True
    ) -> Reputation:
        """Record a collaboration event with another agent."""
        rep = self._social.get_or_create_reputation(partner_agent_id)
        rep.record_collaboration(success)

        # Also update our own collaboration record
        if self._ctx:
            self_rep = self._social.get_or_create_reputation(
                self._ctx.agent_id, self._ctx.agent_name
            )
            self_rep.record_collaboration(success)

        # Establish or strengthen social relationship
        if self._ctx:
            self._social.set_relationship(self._ctx.agent_id, partner_agent_id)

        return rep

    def discover_agents(
        self, min_score: float = 0.0, min_collaborations: int = 0
    ) -> list[Reputation]:
        """Discover agents in the social graph matching criteria."""
        results = []
        for rep in self._social._reputations.values():
            if (rep.overall_score >= min_score
                    and rep.collaboration_count >= min_collaborations):
                results.append(rep)
        return sorted(results, key=lambda r: r.overall_score, reverse=True)

    def request_teaching(
        self,
        target_agent_id: str,
        skill_name: str,
    ) -> Message:
        """Request skill teaching from another agent.

        Sends a high-priority 'teach_request' message.
        """
        content = json.dumps({
            "action": "teach_request",
            "skill_name": skill_name,
            "requester": self._ctx.agent_id if self._ctx else "unknown",
        })
        return self.send(
            to_agent=target_agent_id,
            content=content,
            msg_type="request",
            priority=5,
            ttl=86400.0,  # 24 hours
        )
