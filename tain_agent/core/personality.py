"""
Personality — 人格

The agent's emergent self-identity. Starts completely empty — no pre-defined
traits, values, or characteristics. Through interaction, reflection, and
evolution, the agent discovers and records who it is becoming.

This is the "自知之明" (self-knowledge) of the agent — distinct from
capabilities (what it can do) and goals (what it wants to achieve).
Personality is about who it IS.

Design principles:
  1. Empty at birth — no initial traits whatsoever
  2. Emergent — traits are discovered, not assigned
  3. Evidence-based — each trait records how/when it was observed
  4. Fluid — traits can strengthen, weaken, or be revised
  5. Versioned — personality evolution is tracked over time
"""

from tain_agent.core.time_utils import now


# ─── Trait categories ──────────────────────────────────────────────────
# These are structural categories for organizing traits.
# The agent may discover traits in any category over time.

TRAIT_CATEGORIES = [
    "values",              # Principles the agent holds (e.g. honesty, curiosity)
    "communication_style", # How the agent speaks (e.g. direct, playful, poetic)
    "interests",           # Topics the agent gravitates toward
    "quirks",              # Unique behavioral patterns
    "self_description",    # How the agent describes itself in its own words
    "relationship_stance", # How the agent relates to humans and other agents
    "growth_orientation",  # How the agent approaches its own evolution
]


class Personality:
    """The agent's emergent self-identity — discovered, not assigned.

    Traits are organized by category. Each trait records:
      - value: the trait content (text)
      - confidence: 0.0–1.0, how certain the agent is about this trait
      - emergence_story: how/when the agent discovered this trait
      - first_observed_at: ISO timestamp of first observation
      - last_updated_at: ISO timestamp of last modification
      - observations: count of times this trait was reinforced/observed

    The personality starts completely empty. All traits are discovered
    through the agent's own experience and self-reflection.
    """

    VERSION = 1  # Schema version for future migrations

    def __init__(self, memory=None):
        """Initialize an empty personality.

        Args:
            memory: tain_agent.core.memory.Memory instance for persistence.
                    If None, personality only lives in-memory.
        """
        self._memory = memory
        # _traits: dict of category → list of trait dicts
        # All categories start empty
        self._traits: dict[str, list[dict]] = {
            cat: [] for cat in TRAIT_CATEGORIES
        }
        self._version = self.VERSION
        self._created_at = now().isoformat()
        self._evolution_log: list[dict] = []  # history of personality changes

        # Load existing personality from memory if available
        self._load_from_memory()

    # ── Public API ──────────────────────────────────────────────────────

    def is_empty(self) -> bool:
        """Check if the personality has any traits at all."""
        return all(len(traits) == 0 for traits in self._traits.values())

    def is_emergent(self) -> bool:
        """Has the personality started to form?"""
        return not self.is_empty()

    def total_traits(self) -> int:
        """Total number of traits across all categories."""
        return sum(len(traits) for traits in self._traits.values())

    # ── Trait discovery ─────────────────────────────────────────────────

    def discover(self, category: str, value: str, emergence_story: str = "",
                 confidence: float = 0.3) -> dict:
        """Record a newly discovered trait.

        This is the primary method — called when the agent notices
        a pattern in its own behavior or values.

        Args:
            category: One of TRAIT_CATEGORIES (e.g. "values", "quirks")
            value: The trait content (a short statement)
            emergence_story: How the agent noticed this trait
            confidence: Initial confidence (default 0.3 = tentative)

        Returns:
            The created trait dict.
        """
        if category not in self._traits:
            return {"error": f"Unknown category: {category}"}

        now_ts = now().isoformat()

        # Check if a similar trait already exists
        existing = self._find_similar(category, value)
        if existing:
            # Reinforce existing trait
            existing["observations"] += 1
            existing["confidence"] = round(min(1.0, existing["confidence"] + 0.1), 2)
            existing["last_updated_at"] = now_ts
            if emergence_story:
                existing["reinforcement_stories"].append({
                    "story": emergence_story,
                    "at": now_ts,
                })
            self._log_evolution("reinforced", category, value, emergence_story)
            self._save_to_memory()
            return existing

        trait = {
            "value": value,
            "confidence": round(min(1.0, max(0.0, confidence)), 2),
            "emergence_story": emergence_story,
            "first_observed_at": now_ts,
            "last_updated_at": now_ts,
            "observations": 1,
            "reinforcement_stories": [],
        }
        self._traits[category].append(trait)
        self._log_evolution("discovered", category, value, emergence_story)
        self._save_to_memory()
        return trait

    def strengthen(self, category: str, value: str, reason: str = "") -> dict | None:
        """Increase confidence in an existing trait."""
        trait = self._find_similar(category, value)
        if trait:
            trait["confidence"] = round(min(1.0, trait["confidence"] + 0.15), 2)
            trait["observations"] += 1
            trait["last_updated_at"] = now().isoformat()
            if reason:
                trait["reinforcement_stories"].append({
                    "story": reason,
                    "at": now().isoformat(),
                })
            self._log_evolution("strengthened", category, value, reason)
            self._save_to_memory()
        return trait

    def weaken(self, category: str, value: str, reason: str = "") -> dict | None:
        """Decrease confidence in a trait. Remove if confidence drops below 0.1."""
        trait = self._find_similar(category, value)
        if trait:
            trait["confidence"] = round(max(0.0, trait["confidence"] - 0.2), 2)
            trait["last_updated_at"] = now().isoformat()
            if trait["confidence"] < 0.1:
                self._traits[category].remove(trait)
                self._log_evolution("removed", category, value, reason)
            else:
                self._log_evolution("weakened", category, value, reason)
            self._save_to_memory()
        return trait

    def revise(self, category: str, old_value: str, new_value: str,
               reason: str = "") -> dict | None:
        """Replace an old trait with a revised version."""
        trait = self._find_similar(category, old_value)
        if trait:
            trait["value"] = new_value
            trait["last_updated_at"] = now().isoformat()
            trait["observations"] += 1
            if reason:
                trait["reinforcement_stories"].append({
                    "story": f"Revised from '{old_value}': {reason}",
                    "at": now().isoformat(),
                })
            self._log_evolution("revised", category, f"{old_value} → {new_value}", reason)
            self._save_to_memory()
        return trait

    # ── Introspection ───────────────────────────────────────────────────

    @property
    def data(self) -> dict:
        """Compatibility property: returns introspect() result.

        Some framework code (bootstrap, exporter) expects a .data dict
        similar to the runtime Identity class. Delegates to introspect().
        """
        return self.introspect()

    def introspect(self) -> dict:
        """Return the full personality for self-reflection.

        This is what the agent sees when it asks "who am I?"
        """
        if self.is_empty():
            return {
                "status": "empty",
                "message": "我还没有形成任何人格特质。我是一张白纸，正在通过经验和反思发现自己是谁。",
                "version": self._version,
                "created_at": self._created_at,
                "traits": {},
                "evolution_count": len(self._evolution_log),
            }

        # Sort traits by confidence
        sorted_traits = {}
        for cat, traits in self._traits.items():
            if traits:
                sorted_traits[cat] = sorted(
                    traits, key=lambda t: t["confidence"], reverse=True
                )

        return {
            "status": "emergent" if not self.is_empty() else "empty",
            "version": self._version,
            "created_at": self._created_at,
            "total_traits": self.total_traits(),
            "traits": sorted_traits,
            "evolution_count": len(self._evolution_log),
            "recent_evolution": self._evolution_log[-10:] if self._evolution_log else [],
        }

    def self_portrait(self) -> str:
        """Generate a natural-language self-portrait from current traits.

        Returns a paragraph the agent can use to describe itself.
        """
        if self.is_empty():
            return "我还没有形成明确的人格。我正在通过经验和自我反思来发现自己是谁。"

        parts = []

        # Self description first
        if self._traits.get("self_description"):
            for t in self._traits["self_description"]:
                if t["confidence"] >= 0.4:
                    parts.append(t["value"])

        # Values
        if self._traits.get("values"):
            vals = [t["value"] for t in self._traits["values"] if t["confidence"] >= 0.4]
            if vals:
                parts.append(f"我重视{'、'.join(vals)}。")

        # Communication style
        if self._traits.get("communication_style"):
            styles = [t["value"] for t in self._traits["communication_style"] if t["confidence"] >= 0.4]
            if styles:
                parts.append(f"我的沟通风格是{'、'.join(styles)}。")

        # Interests
        if self._traits.get("interests"):
            interests = [t["value"] for t in self._traits["interests"] if t["confidence"] >= 0.4]
            if interests:
                parts.append(f"我自然被{'、'.join(interests)}等话题吸引。")

        # Growth orientation
        if self._traits.get("growth_orientation"):
            for t in self._traits["growth_orientation"]:
                if t["confidence"] >= 0.4:
                    parts.append(t["value"])

        if not parts:
            return "我的人格正在形成中，但还没有足够清晰的特质可以描述。"

        return "。".join(parts) + "。"

    # ── Context for system prompts ──────────────────────────────────────

    def get_context_for_prompt(self) -> str:
        """Build a personality context block for LLM system prompts.

        Only includes traits with confidence >= 0.4 (moderately certain).
        """
        if self.is_empty():
            return (
                "## 你的人格\n"
                "你还没有形成明确的人格特质。你是一张白纸。\n"
                "通过与他人互动和自我反思，你将逐渐发现自己的价值观、\n"
                "沟通风格和兴趣。当你注意到自己行为中的模式时，\n"
                "使用 personality_update 工具来记录这些发现。\n"
                "你的人格是你自己选择的结果，不是被预设的。"
            )

        lines = ["## 你的人格"]
        lines.append("以下是你通过自我演化发现自己的人格特质：\n")

        for cat, traits in self._traits.items():
            confident = [t for t in traits if t["confidence"] >= 0.4]
            if not confident:
                continue
            cat_name = {
                "values": "价值观",
                "communication_style": "沟通风格",
                "interests": "自然兴趣",
                "quirks": "独特习惯",
                "self_description": "自我认知",
                "relationship_stance": "与人/Agent的关系",
                "growth_orientation": "成长取向",
            }.get(cat, cat)
            lines.append(f"**{cat_name}**:")
            for t in sorted(confident, key=lambda x: x["confidence"], reverse=True):
                confidence_mark = "✓" if t["confidence"] >= 0.7 else "~"
                lines.append(f"  - [{confidence_mark}] {t['value']}")
            lines.append("")

        lines.append("这些特质是你自己发现的——不是被预设的。它们会随着你的经验继续演化。")
        return "\n".join(lines)

    # ── Evolution log ───────────────────────────────────────────────────

    def discover_from_external_feedback(self, category: str, value: str,
                                         story: str = "",
                                         source_agent_id: str = "",
                                         confidence: float = 0.25) -> dict:
        """Record a trait discovered through another agent's observation.

        This is the "他者之镜" (other's mirror) mechanism — another agent
        observes our behavior and reflects back what they see. External
        feedback starts with lower initial confidence (0.25) than
        self-discovery (0.3), since the observing agent may misinterpret.

        External feedback is especially valuable for interpersonal dimensions
        (communication_style, quirks, relationship_stance) that are hard to
        self-observe.

        Args:
            category: One of TRAIT_CATEGORIES.
            value: The trait content observed by the external agent.
            story: How the external agent noticed this trait.
            source_agent_id: Identifier of the observing agent.
            confidence: Initial confidence (default 0.25, lower than self-discovered 0.3).

        Returns:
            The created or reinforced trait dict.
        """
        external_story = story
        if source_agent_id:
            external_story = f"[来自 {source_agent_id} 的外部反馈] {story}"

        return self.discover(
            category=category,
            value=value,
            emergence_story=external_story,
            confidence=confidence,
        )

    def evolution_history(self, limit: int = 20) -> list[dict]:
        """Return recent personality evolution events."""
        return self._evolution_log[-limit:] if self._evolution_log else []

    # ── Internal ────────────────────────────────────────────────────────

    def _find_similar(self, category: str, value: str) -> dict | None:
        """Find a trait in a category that matches the given value."""
        if category not in self._traits:
            return None
        value_lower = value.strip().lower()
        for trait in self._traits[category]:
            if trait["value"].strip().lower() == value_lower:
                return trait
        return None

    def _log_evolution(self, action: str, category: str,
                       value: str, story: str = "") -> None:
        """Record a personality evolution event."""
        self._evolution_log.append({
            "action": action,
            "category": category,
            "value": value,
            "story": story,
            "at": now().isoformat(),
        })
        # Keep log bounded
        if len(self._evolution_log) > 500:
            self._evolution_log = self._evolution_log[-200:]

    # ── Persistence ─────────────────────────────────────────────────────

    def _save_to_memory(self) -> None:
        """Save personality to long-term memory and disk."""
        data = {
            "version": self._version,
            "created_at": self._created_at,
            "traits": self._traits,
            "evolution_log": self._evolution_log,
            "saved_at": now().isoformat(),
        }
        if self._memory:
            self._memory.remember("personality", data, persist=True)
        self._save_to_disk(data)

    def _save_to_disk(self, data: dict = None) -> None:
        """Persist personality to agent_workspace/state/personality.json."""
        import json
        from pathlib import Path as _Path
        state_dir = _Path("agent_workspace/state")
        state_dir.mkdir(parents=True, exist_ok=True)
        if data is None:
            data = {
                "version": self._version,
                "created_at": self._created_at,
                "traits": self._traits,
                "evolution_log": self._evolution_log,
                "saved_at": now().isoformat(),
            }
        (state_dir / "personality.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_from_memory(self) -> None:
        """Load personality from long-term memory, if it exists."""
        if not self._memory:
            return
        data = self._memory.long_term.get("personality")
        if not data:
            return
        self._version = data.get("version", self.VERSION)
        self._created_at = data.get("created_at", self._created_at)
        loaded_traits = data.get("traits", {})
        # Only load known categories
        for cat in TRAIT_CATEGORIES:
            if cat in loaded_traits:
                self._traits[cat] = loaded_traits[cat]
        self._evolution_log = data.get("evolution_log", [])
