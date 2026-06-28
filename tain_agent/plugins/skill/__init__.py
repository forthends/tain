"""SkillPlugin — manages the agent's skill catalog with maturity tracking."""

from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol
from tain_agent.plugins.skill.composer import compose_skills
from tain_agent.plugins.skill.model import MaturityLevel, Skill, Step

logger = logging.getLogger(__name__)


class SkillPlugin:
    """Plugin that owns the agent's skill catalog.

    Skills improve with practice (record_use) and can be composed from
    sub-skills. Maturity tracks proficiency from NOVICE to MASTER.

    Required PluginProtocol methods: initialize, shutdown, health_check,
    snapshot, restore.
    Optional PRAL hooks: on_cycle_start, on_cycle_end, enrich_prompt,
    on_llm_response.
    """

    version = "1.0.0"

    def __init__(self):
        self._ctx: AgentContext | None = None
        self._skills: dict[str, Skill] = {}
        self._persist_path: Path | None = None
        self._catalog_dirty = False

    # ── PluginProtocol ──────────────────────────────────────────────

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        self._persist_path = ctx.workspace_path / "capability" / "skills" / "catalog.json"
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def shutdown(self) -> None:
        self._save()
        self._skills.clear()
        self._ctx = None

    def health_check(self) -> HealthStatus:
        if self._ctx is None:
            return HealthStatus(status="critical", alerts=["not initialized"])
        novice = sum(1 for s in self._skills.values() if s.maturity <= MaturityLevel.NOVICE)  # type: ignore[operator]
        expert = sum(1 for s in self._skills.values() if s.maturity >= MaturityLevel.EXPERT)  # type: ignore[operator]
        metrics = {
            "skill_count": float(len(self._skills)),
            "novice_count": float(novice),
            "expert_count": float(expert),
        }
        return HealthStatus(status="ok", metrics=metrics)

    def snapshot(self) -> dict[str, Any]:
        return {
            "skills": {name: s.to_dict() for name, s in self._skills.items()},
        }

    def restore(self, data: dict[str, Any]) -> None:
        if "skills" in data:
            self._skills = {
                name: Skill.from_dict(sdata)
                for name, sdata in data["skills"].items()
            }

    # ── PRAL hooks ──────────────────────────────────────────────────

    def on_cycle_start(self, cycle: int) -> None:
        pass

    def on_cycle_end(self, cycle: int) -> None:
        if self._catalog_dirty:
            self._save()
            self._catalog_dirty = False

    def enrich_prompt(self, base: str) -> str:
        if not self._skills:
            return base

        parts = [base, "", "## 技能目录 (Skill Catalog)"]
        for name, skill in sorted(self._skills.items()):
            parts.append(
                f"- **{skill.display_name}** ({name}) "
                f"[{skill.maturity.name}] "
                f"成功率: {skill.success_rate:.0%} "
                f"({skill.success_count}/{skill.usage_count})"
            )

        return "\n".join(parts)

    def on_llm_response(self, response: Any) -> None:
        pass

    # ── Persistence ─────────────────────────────────────────────────

    def _save(self) -> None:
        if self._persist_path is None:
            return
        try:
            data = {name: s.to_dict() for name, s in self._skills.items()}
            self._persist_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save skill catalog: %s", e)

    def _load(self) -> None:
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            self._skills = {
                name: Skill.from_dict(sdata)
                for name, sdata in data.items()
            }
        except Exception as e:
            logger.warning("Failed to load skill catalog: %s — starting fresh", e)
            self._skills = {}

    # ── Skill API ───────────────────────────────────────────────────

    def register(self, skill: Skill) -> None:
        """Register a new skill."""
        self._skills[skill.name] = skill
        self._catalog_dirty = True

    def get(self, name: str) -> Skill | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def list_skills(self, min_maturity: MaturityLevel | None = None) -> list[Skill]:
        """List all skills, optionally filtered by minimum maturity."""
        skills = list(self._skills.values())
        if min_maturity is not None:
            skills = [s for s in skills if s.maturity >= min_maturity]
        return sorted(skills, key=lambda s: s.maturity.value, reverse=True)

    def practice(self, name: str, success: bool = True) -> Skill | None:
        """Record practice for a skill. Returns updated skill or None."""
        skill = self._skills.get(name)
        if skill is None:
            return None
        skill.record_use(success)
        self._catalog_dirty = True
        return skill

    def teach(
        self,
        skill_name: str,
        target_agent_id: str,
    ) -> dict[str, Any] | None:
        """Prepare a skill for teaching to another agent.

        Returns a serializable dict the receiving agent can use to
        register the skill, or None if the skill is not found.
        """
        skill = self._skills.get(skill_name)
        if skill is None:
            return None
        return {
            "skill": skill.to_dict(),
            "teacher_agent_id": self._ctx.agent_id if self._ctx else "",
            "target_agent_id": target_agent_id,
        }

    def compose(
        self,
        name: str,
        display_name: str,
        description: str,
        sub_skill_names: list[str],
        workflow: list[Step] | None = None,
    ) -> Skill | None:
        """Compose a new skill from existing sub-skills.

        Returns the composed Skill, or None if any sub-skill is missing.
        """
        sub_skills: list[Skill] = []
        for sname in sub_skill_names:
            s = self._skills.get(sname)
            if s is None:
                return None
            sub_skills.append(s)

        composed = compose_skills(
            name=name,
            display_name=display_name,
            description=description,
            sub_skills=sub_skills,
            workflow=workflow,
        )
        self._skills[name] = composed
        self._catalog_dirty = True
        return composed
