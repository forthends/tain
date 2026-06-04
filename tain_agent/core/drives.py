"""
Intrinsic Drive System — 内驱力引擎

Phase 2 core mechanism for breaking the "passive maintenance" trap.

Four competing drives (curiosity, mastery, creation, conservation) create
internal tension that drives behavior even when all system metrics are healthy.
Personality emerges from the relative strengths of these drives.

Key design properties:
  - Drives are randomly initialized per instance → different identities
  - Drives are satisfied by corresponding actions → feedback loop
  - Neglected drives gradually intensify → ensures behavioral diversity
  - The "exploration score" from drives feeds the improvement loop → breaks
    the zero-score deadlock that caused Phase 1's passive maintenance
"""

import random
from tain_agent.core.time_utils import now


# ─── Drive definitions ─────────────────────────────────────────────────

DRIVE_DEFINITIONS = {
    "curiosity": {
        "name_zh": "好奇",
        "description": "探索新领域、学习新知识",
        "excess_symptom": "浅尝辄止，从不深入",
        "satisfied_by": [
            "web_search", "web_fetch", "explore_directory", "read_file",
            "observe_environment", "get_current_time",
        ],
        "default_intensity": 0.5,
    },
    "mastery": {
        "name_zh": "精进",
        "description": "深入打磨已有能力",
        "excess_symptom": "陷入局部最优，忽视新机会",
        "satisfied_by": [
            "modify_self_file", "run_improvement_pipeline",
            "assess_capabilities", "regression_tester",
        ],
        "default_intensity": 0.4,
    },
    "creation": {
        "name_zh": "创造",
        "description": "锻造新工具、生成新知识",
        "excess_symptom": "只造不用，工具堆积",
        "satisfied_by": [
            "forge_tool", "write_file", "execute_code",
            "sub_agent_spawn",
        ],
        "default_intensity": 0.5,
    },
    "conservation": {
        "name_zh": "守成",
        "description": "优化、整理、维护存量",
        "excess_symptom": "被动养护，缺乏进取",
        "satisfied_by": [
            "assess_capabilities", "pipeline_status",
            "evolve_report", "complete_goal",
        ],
        "default_intensity": 0.3,
    },
}


class DriveSystem:
    """Manages the agent's four intrinsic drives and the exploration engine.

    Drives compete for the agent's attention. Each action satisfies some drives
    and neglects others, creating a natural ebb and flow of motivation.
    """

    def __init__(self, drives_config: dict = None, exploration_config: dict = None,
                 memory=None):
        self._memory = memory
        self._history: list[dict] = []

        # Initialize drives from config or randomize
        cfg = drives_config or {}
        self.drives: dict[str, float] = {}
        for name, defn in DRIVE_DEFINITIONS.items():
            if name in cfg and cfg[name] is not None:
                self.drives[name] = max(0.0, min(1.0, float(cfg[name])))
            else:
                # Random initialization with the default as mean
                base = defn["default_intensity"]
                self.drives[name] = round(
                    max(0.1, min(0.95, random.uniform(base - 0.25, base + 0.25))), 2
                )

        # Exploration engine config
        expl = exploration_config or {}
        self._curiosity_bonus_rate = expl.get("curiosity_bonus_rate", 0.05)
        self._max_curiosity_bonus = expl.get("max_curiosity_bonus", 0.30)
        self._novelty_weight = expl.get("novelty_weight", 0.20)
        self._idle_pressure_rate = expl.get("idle_pressure_rate", 0.10)
        self._max_idle_pressure = expl.get("max_idle_pressure", 0.40)

        # Runtime state
        self._idle_cycles = 0
        self._unexplored_ratio = 1.0
        self._days_since_last_action = 0
        self._last_action_at = now()
        self._explored_tool_types: set[str] = set()
        self._explored_domains: set[str] = set()

        self._load_from_memory()

    # ── Public API ──────────────────────────────────────────────────

    def get_profile(self) -> dict:
        """Return the current drive profile for display/decision."""
        dominant = max(self.drives, key=self.drives.get)
        return {
            "drives": dict(self.drives),
            "dominant_drive": dominant,
            "dominant_name": DRIVE_DEFINITIONS[dominant]["name_zh"],
            "personality_hint": self._derive_personality_hint(),
            "exploration": self.get_exploration_state(),
        }

    def _derive_personality_hint(self) -> str:
        """Derive a personality tendency from the current drive balance."""
        c = self.drives
        if c["curiosity"] > 0.7 and c["creation"] > 0.6:
            return "探索者-建造者：倾向于发现新领域并为其构建工具"
        if c["curiosity"] > 0.7 and c["mastery"] < 0.3:
            return "漫游者：享受广度探索，但可能缺乏深度"
        if c["mastery"] > 0.7:
            return "工匠：倾向于深入打磨和完善已有能力"
        if c["creation"] > 0.7:
            return "狂热建造者：热衷于创造新工具，可能忽视维护"
        if c["conservation"] > 0.6 and c["curiosity"] < 0.3:
            return "守护者：倾向于维护和保护现有成果"
        if max(c.values()) - min(c.values()) < 0.2:
            return "平衡者：各种驱动力相对均衡，尚未形成明显倾向"
        return "演化中的存在：驱动力仍在调整中"

    # ── Action Feedback ─────────────────────────────────────────────

    def record_action(self, tool_name: str) -> dict:
        """Record an action and update drive satisfaction levels.

        The action satisfies the drives it maps to (temporarily lowering them)
        and the neglected drives gradually intensify.

        Returns the drive delta for logging.
        """
        deltas = {}

        # Satisfaction: drives that match this action decrease
        for name, defn in DRIVE_DEFINITIONS.items():
            if tool_name in defn["satisfied_by"]:
                # Satisfied drive — reduce intensity (consummatory effect)
                decrease = round(random.uniform(0.03, 0.08), 2)
                old = self.drives[name]
                self.drives[name] = round(max(0.05, old - decrease), 2)
                deltas[name] = round(self.drives[name] - old, 2)

        # Neglect: drives NOT satisfied by this action increase slightly
        satisfied_drives = {
            name for name, defn in DRIVE_DEFINITIONS.items()
            if tool_name in defn["satisfied_by"]
        }
        for name in self.drives:
            if name not in satisfied_drives:
                increase = round(random.uniform(0.01, 0.04), 2)
                old = self.drives[name]
                self.drives[name] = round(min(0.95, old + increase), 2)
                if name not in deltas:
                    deltas[name] = round(self.drives[name] - old, 2)

        # Update state
        self._idle_cycles = 0
        self._last_action_at = now()
        self._track_tool_type(tool_name)

        self._log_event("action", tool_name, deltas)
        self._save_to_memory()
        return deltas

    def record_idle_cycle(self) -> None:
        """Record a cycle where the agent took no productive action.

        This increases the exploration pressure — idle cycles make the agent
        increasingly likely to try something new.
        """
        self._idle_cycles += 1

        # Neglected drives intensify during idle periods
        for name in self.drives:
            increase = round(random.uniform(0.005, 0.02), 3)
            self.drives[name] = round(min(0.95, self.drives[name] + increase), 2)

        self._log_event("idle", f"cycle_{self._idle_cycles}", {})

    # ── Exploration Engine (Section 2.6) ────────────────────────────

    def compute_exploration_score(self) -> float:
        """Compute the exploration score that supplements gap-driven improvement.

        This is THE mechanism that breaks the Phase 1 "all zeros → passive
        maintenance" trap. Even when all system metrics are healthy, the
        exploration score can trigger new cycles of activity.

        Components:
          1. Curiosity bonus: grows with idle cycles (驱动力驱动的探索冲动)
          2. Novelty bonus: proportional to unexplored space (未探索空间的吸引力)
          3. Idle pressure: accumulates over real time (时间带来的压力)
        """
        # 1. Curiosity bonus — scales with idle cycles and curiosity drive
        curiosity_bonus = min(
            self._max_curiosity_bonus,
            self._idle_cycles * self._curiosity_bonus_rate * self.drives["curiosity"]
        )

        # 2. Novelty bonus — unexplored space pulls the agent outward
        novelty_bonus = self._unexplored_ratio * self._novelty_weight * self.drives["curiosity"]

        # 3. Idle pressure — entropy/time pressure
        idle_pressure = min(
            self._max_idle_pressure,
            self._days_since_last_action * self._idle_pressure_rate
        )

        total = curiosity_bonus + novelty_bonus + idle_pressure
        return round(min(1.0, total), 4)

    def get_exploration_state(self) -> dict:
        """Get current exploration engine state."""
        return {
            "idle_cycles": self._idle_cycles,
            "unexplored_ratio": round(self._unexplored_ratio, 3),
            "days_since_last_action": round(self._days_since_last_action, 1),
            "curiosity_bonus": round(
                min(self._max_curiosity_bonus,
                    self._idle_cycles * self._curiosity_bonus_rate * self.drives["curiosity"]), 3
            ),
            "novelty_bonus": round(
                self._unexplored_ratio * self._novelty_weight * self.drives["curiosity"], 3
            ),
            "idle_pressure": round(
                min(self._max_idle_pressure, self._days_since_last_action * self._idle_pressure_rate), 3
            ),
            "exploration_score": self.compute_exploration_score(),
        }

    def update_explored_space(self, unexplored_ratio: float) -> None:
        """Update the estimate of how much unexplored space remains.

        Called by the knowledge system to inform the novelty bonus.
        """
        self._unexplored_ratio = max(0.0, min(1.0, unexplored_ratio))

    def update_time_pressure(self, days_since: float) -> None:
        """Update the real-time idle pressure."""
        self._days_since_last_action = max(0.0, days_since)

    # ── Drive Suggestions ───────────────────────────────────────────

    def suggest_action_type(self) -> str:
        """Suggest what kind of action the agent should take, based on
        the currently most neglected (highest intensity) drive.
        """
        top_drive = max(self.drives, key=self.drives.get)

        suggestions = {
            "curiosity": "探索一个新领域或学习一件你不知道的事",
            "mastery": "深入打磨一个已有工具或优化一段代码",
            "creation": "锻造一个新工具或创造一个有用的东西",
            "conservation": "检查和维护现有工具、整理知识园林",
        }

        return suggestions.get(top_drive, "根据你的判断选择一个行动方向")

    def get_action_weights(self) -> dict[str, float]:
        """Return tool-category weights derived from current drive intensities.

        Categories map to drives:
          - observation → curiosity (read, search, explore)
          - optimization → mastery (improve, refine, test)
          - creation → creation (forge, write, generate)
          - maintenance → conservation (assess, report, organize)

        Returns:
            Dict of category → weight (0.0–1.0), normalized to sum to 1.0.
        """
        raw = {
            "observation": self.drives.get("curiosity", 0.5),
            "optimization": self.drives.get("mastery", 0.5),
            "creation": self.drives.get("creation", 0.5),
            "maintenance": self.drives.get("conservation", 0.5),
        }
        total = sum(raw.values())
        if total == 0:
            return {k: 0.25 for k in raw}
        return {k: round(v / total, 3) for k, v in raw.items()}

    def get_exploration_prompt(self) -> str:
        """If exploration pressure is high, return a prompt injection
        suggesting the agent try something new. Returns empty string
        if exploration score is low.
        """
        score = self.compute_exploration_score()
        if score < 0.5:
            return ""

        top_drive = max(self.drives, key=self.drives.get)
        drive_name = DRIVE_DEFINITIONS[top_drive]["name_zh"]

        suggestions = {
            "curiosity": "你感到一股强烈的探索冲动——有没有一个你一直好奇但从未深入了解的领域？",
            "mastery": "你感到精进的渴望——有没有一个工具或技能你一直想打磨到极致？",
            "creation": "创造的冲动在你心中涌动——有什么东西你想带到这个世界上来？",
            "conservation": "你觉得是时候整理了——有没有积压的工作需要清理和优化？",
        }
        return f"[内驱力信号 · {drive_name}] {suggestions.get(top_drive, '')}"

    def dominate_drive(self) -> str:
        """Return the name of the currently dominant drive."""
        return max(self.drives, key=self.drives.get)

    def get_target_domain(self) -> str:
        """Return a domain description for the currently dominant drive.

        Used by agent loop to fill goal templates with drive-appropriate
        target descriptions. The caller should refine this with specific
        tool/module names from the capability registry.
        """
        dominant = max(self.drives, key=self.drives.get)
        domains = {
            "curiosity": "a new knowledge domain",
            "mastery": "an existing tool or module",
            "creation": "a capability gap that needs a new tool",
            "conservation": "a system module that needs maintenance",
        }
        return domains.get(dominant, "an area worth attention")

    # ── Internal ────────────────────────────────────────────────────

    def _track_tool_type(self, tool_name: str) -> None:
        """Track which tool types have been used (for novelty calculation)."""
        self._explored_tool_types.add(tool_name)

    def _log_event(self, event_type: str, detail: str, deltas: dict) -> None:
        self._history.append({
            "type": event_type,
            "detail": detail,
            "deltas": deltas,
            "drives_snapshot": dict(self.drives),
            "at": now().isoformat(),
        })
        if len(self._history) > 200:
            self._history = self._history[-100:]

    # ── Persistence ─────────────────────────────────────────────────

    def _save_to_memory(self) -> None:
        if not self._memory:
            return
        self._memory.remember("drives", {
            "drives": dict(self.drives),
            "idle_cycles": self._idle_cycles,
            "unexplored_ratio": self._unexplored_ratio,
            "last_action_at": self._last_action_at.isoformat(),
        }, persist=True)

    def _load_from_memory(self) -> None:
        if not self._memory:
            return
        data = self._memory.long_term.get("drives")
        if not data:
            return
        saved_drives = data.get("drives", {})
        for name in self.drives:
            if name in saved_drives:
                self.drives[name] = saved_drives[name]
        self._idle_cycles = data.get("idle_cycles", 0)
        self._unexplored_ratio = data.get("unexplored_ratio", 1.0)
        last_action_str = data.get("last_action_at")
        if last_action_str:
            try:
                from datetime import datetime
                self._last_action_at = datetime.fromisoformat(last_action_str)
                self._days_since_last_action = (now() - self._last_action_at).total_seconds() / 86400
            except (ValueError, TypeError):
                pass
