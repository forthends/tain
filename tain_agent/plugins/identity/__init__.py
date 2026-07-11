"""IdentityPlugin — manages the agent's complete identity profile."""

from __future__ import annotations
import json
import logging
from pathlib import Path
from tain_agent.kernel.protocol import AgentContext, HealthStatus, PluginProtocol
from tain_agent.plugins.identity.model import AgentIdentity, EvolutionEvent

logger = logging.getLogger(__name__)


class _PersonalityAdapter:
    """Adapter that exposes Personality-like API from IdentityPlugin traits."""

    def __init__(self, plugin: "IdentityPlugin"):
        self._plugin = plugin

    def get_context_for_prompt(self) -> str:
        """Build a prompt context string from confident traits."""
        return self._plugin._trait_context()

    def introspect(self) -> dict:
        """Return a summary of current personality traits."""
        if self._plugin.identity is None:
            return {"traits": {}}
        result = {"traits": {}}
        for cat, traits in self._plugin.identity.traits.items():
            result["traits"][cat] = [
                {"value": t.get("value", ""), "confidence": t.get("confidence", 0)}
                for t in traits
            ]
        return result

    def auto_observe(self, tool_names: list[str], text_parts: list[str]) -> None:
        """Behavioral observation of tool usage to auto-discover traits."""
        self._plugin._observe_traits(tool_names, text_parts)


class IdentityPlugin:
    """Plugin that owns AgentIdentity — who the agent is, what it values, its boundaries."""

    version = "1.0.0"

    def __init__(self):
        self._ctx: AgentContext | None = None
        self.identity: AgentIdentity | None = None
        self._profile_path: Path | None = None

    @property
    def personality(self):
        """Return a Personality adapter backed by IdentityPlugin's trait data.

        Provides get_context_for_prompt() and introspect() for dialogue.py
        compatibility. Reads/writes traits through self.identity.traits.
        """
        return _PersonalityAdapter(self)

    # ── PluginProtocol ───────────────────────────────────────────

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        self._profile_path = ctx.workspace_path / "cognitive" / "identity" / "profile.json"
        self._profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.identity = self._load_or_create()

    def shutdown(self) -> None:
        self._save()
        self.identity = None

    def health_check(self) -> HealthStatus:
        if self.identity is None:
            return HealthStatus(status="critical", alerts=["identity not initialized"])
        metrics = {
            "expertise_count": float(len(self.identity.expertise_domains)),
            "values_count": float(len(self.identity.values)),
            "traits_total": float(sum(len(t) for t in self.identity.traits.values())),
            "goals_active": float(sum(1 for g in self.identity.goals if g.status == "active")),
            "skill_catalog_size": float(len(self.identity.skill_catalog)),
        }
        return HealthStatus(status="ok", metrics=metrics)

    def snapshot(self) -> dict:
        return self.identity.to_dict() if self.identity else {}

    def restore(self, data: dict) -> None:
        pass  # identity always loads from disk

    # Optional PRAL hooks
    def on_cycle_start(self, cycle: int) -> None: pass
    def on_cycle_end(self, cycle: int) -> None: pass

    def enrich_prompt(self, base: str) -> str:
        if self.identity is None:
            return base
        parts = [base, "", "## 你的身份"]
        if self.identity.role:
            parts.append(f"角色: {self.identity.role}")
        if self.identity.mission:
            parts.append(f"使命: {self.identity.mission}")
        if self.identity.expertise_domains:
            domains = ", ".join(f"{d.domain}(L{d.proficiency})" for d in self.identity.expertise_domains)
            parts.append(f"专长领域: {domains}")
        if self.identity.constraints.max_autonomy_level.value < 4:
            parts.append(f"自主等级: {self.identity.constraints.max_autonomy_level.name} — 创建工具需要人类审批")
        # Include personality context from traits
        trait_ctx = self._trait_context()
        if trait_ctx:
            parts.append(trait_ctx)
        return "\n".join(parts)

    def on_llm_response(self, response) -> None:
        if self.identity and response.tool_calls:
            tool_names = [tc.name for tc in response.tool_calls]
            self._observe_traits(tool_names, response.text_blocks)

    # ── Persistence ──────────────────────────────────────────────

    def _load_or_create(self) -> AgentIdentity:
        if self._profile_path and self._profile_path.exists():
            try:
                data = json.loads(self._profile_path.read_text(encoding="utf-8"))
                return AgentIdentity(**data)
            except Exception as e:
                logger.warning("Failed to load identity profile: %s — creating new", e)
        identity = AgentIdentity(
            agent_id=self._ctx.agent_id,
            name=self._ctx.agent_name,
            evolution_mode=self._ctx.evolution_mode,
        )
        if self._ctx.evolution_mode == "specified":
            role = self._ctx.config.get("identity", {}).get("role", "")
            desc = self._ctx.config.get("identity", {}).get("role_description", "")
            identity.awaken_from_role(role, desc)
        return identity

    def _save(self) -> None:
        if self.identity and self._profile_path:
            self._profile_path.write_text(
                json.dumps(self.identity.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _trait_context(self) -> str:
        if not self.identity:
            return ""
        confident = {}
        for cat, traits in self.identity.traits.items():
            cat_traits = [t for t in traits if t.get("confidence", 0) >= 0.4]
            if cat_traits:
                confident[cat] = cat_traits
        if not confident:
            return ""
        lines = ["", "## 你的人格特质", ""]
        cat_names = {
            "values": "价值观", "communication_style": "沟通风格",
            "interests": "自然兴趣", "quirks": "独特习惯",
            "self_description": "自我认知", "relationship_stance": "与人/Agent的关系",
            "growth_orientation": "成长取向",
        }
        for cat, traits in confident.items():
            lines.append(f"**{cat_names.get(cat, cat)}**:")
            for t in sorted(traits, key=lambda x: x.get("confidence", 0), reverse=True):
                mark = "✓" if t.get("confidence", 0) >= 0.7 else "~"
                lines.append(f"  - [{mark}] {t['value']}")
            lines.append("")
        return "\n".join(lines)

    def _observe_traits(self, tool_names: list[str], text_parts: list[str]) -> None:
        """Behavioral observation — auto-discover traits from tool usage."""
        from tain_agent.core.personality import Personality
        temp = Personality()
        temp._traits = dict(self.identity.traits)  # copy current state
        temp.auto_observe(tool_names, text_parts)
        self.identity.traits = dict(temp._traits)  # copy back
