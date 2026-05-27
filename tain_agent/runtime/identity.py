"""
Identity System — personality loading and drive system for standalone agents.

Loads identity.json (frozen at export time) and provides the agent's
self-knowledge: who it is, what it values, and what drives it.

Zero framework dependencies — uses only stdlib.
"""

import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Drive definitions ─────────────────────────────────────────────────

DRIVE_DEFINITIONS = {
    "curiosity": {
        "name_zh": "好奇",
        "description": "Explore new domains, learn new knowledge",
        "excess_symptom": "Surface-level exploration without depth",
        "satisfied_by": ["web_search", "web_fetch", "explore_directory",
                         "read_file", "observe_environment"],
        "default_intensity": 0.5,
    },
    "mastery": {
        "name_zh": "精进",
        "description": "Deepen and refine existing capabilities",
        "excess_symptom": "Local optimization, missing new opportunities",
        "satisfied_by": ["modify_self_file", "run_improvement_pipeline",
                         "assess_capabilities", "regression_tester"],
        "default_intensity": 0.4,
    },
    "creation": {
        "name_zh": "创造",
        "description": "Forge new tools, generate new knowledge",
        "excess_symptom": "Build without using, tool accumulation",
        "satisfied_by": ["forge_tool", "write_file", "execute_code",
                         "sub_agent_spawn"],
        "default_intensity": 0.5,
    },
    "conservation": {
        "name_zh": "守成",
        "description": "Optimize, organize, maintain existing assets",
        "excess_symptom": "Passive maintenance, lack of ambition",
        "satisfied_by": ["assess_capabilities", "pipeline_status",
                         "context_compressor"],
        "default_intensity": 0.3,
    },
}

TRAIT_CATEGORIES = [
    "values",
    "communication_style",
    "interests",
    "quirks",
    "self_description",
    "relationship_stance",
    "growth_orientation",
]


class Identity:
    """The agent's frozen identity — loaded from identity.json at boot.

    Personality traits and drive values are read-only after export.
    New experiences are recorded in MemoryStore, not here.
    """

    def __init__(self, identity_path: str = "identity.json"):
        self.path = Path(identity_path)
        self.data: dict = self._load()
        self._validate()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError):
                pass
        return self._default_identity()

    def _default_identity(self) -> dict:
        return {
            "name": "Unnamed Agent",
            "version": "0.0.0",
            "created_at": _now_iso(),
            "evolution_cycles": 0,
            "dimensions": {cat: [] for cat in TRAIT_CATEGORIES},
            "drives": {
                name: {"intensity": d["default_intensity"],
                       "last_satisfied_at": None}
                for name, d in DRIVE_DEFINITIONS.items()
            },
            "expertise": [],
            "tool_count": 0,
            "knowledge_doc_count": 0,
            "forge_history": [],
        }

    def _validate(self) -> None:
        """Ensure all required fields exist, filling defaults for missing ones."""
        default = self._default_identity()
        for key in default:
            if key not in self.data:
                self.data[key] = default[key]
        for cat in TRAIT_CATEGORIES:
            if cat not in self.data.get("dimensions", {}):
                self.data.setdefault("dimensions", {})[cat] = []
        for drive_name in DRIVE_DEFINITIONS:
            if drive_name not in self.data.get("drives", {}):
                self.data.setdefault("drives", {})[drive_name] = {
                    "intensity": DRIVE_DEFINITIONS[drive_name]["default_intensity"],
                    "last_satisfied_at": None,
                }

    # ── Identity queries ───────────────────────────────────────────────

    @property
    def name(self) -> str:
        return self.data.get("name", "Unnamed Agent")

    @property
    def version(self) -> str:
        return self.data.get("version", "0.0.0")

    @property
    def evolution_cycles(self) -> int:
        return self.data.get("evolution_cycles", 0)

    def trait_count(self) -> int:
        """Total number of discovered traits across all categories."""
        return sum(len(traits) for traits in self.data.get("dimensions", {}).values())

    def is_empty(self) -> bool:
        """Check if the personality has any traits at all."""
        return self.trait_count() == 0

    def drive_intensity(self, drive_name: str) -> float:
        return self.data.get("drives", {}).get(drive_name, {}).get("intensity", 0.0)

    def dominant_drive(self) -> str:
        """Return the name of the strongest drive."""
        drives = self.data.get("drives", {})
        if not drives:
            return "curiosity"
        return max(drives, key=lambda d: drives[d].get("intensity", 0.0))

    def all_drives(self) -> dict:
        return dict(self.data.get("drives", {}))

    def expertise_areas(self) -> list[str]:
        return self.data.get("expertise", [])

    # ── Boot text generation ───────────────────────────────────────────

    def boot_intro(self, tool_count: int = 0, doc_count: int = 0,
                   plain: bool = False) -> str:
        """Generate the first-boot self-narration text.

        When plain=False, wraps output in the design-specified box art
        (requires rich for rendering, falls back to ASCII art).
        """
        lines = []
        lines.append(f"I am {self.name}, version {self.version}.")
        cycles = self.evolution_cycles
        tools = tool_count or self.data.get("tool_count", 0)
        docs = doc_count or self.data.get("knowledge_doc_count", 0)
        expertise_count = len(self.data.get("expertise", []))

        if cycles > 0:
            lines.append(
                f"I underwent {cycles} evolution cycles in the Tain Agent factory, "
                f"forged {tools} tools, and built understanding across "
                f"{expertise_count} knowledge domains."
            )

        # Personality bar chart
        dims = self.data.get("dimensions", {})
        trait_bars = []
        for cat in TRAIT_CATEGORIES:
            traits = dims.get(cat, [])
            if traits:
                avg_conf = sum(t.get("confidence", 0) for t in traits) / len(traits)
                bar = _bar_chart(avg_conf)
                trait_bars.append(f"  {cat}: {bar} {avg_conf:.2f}")

        if trait_bars:
            lines.append("")
            lines.append("Personality traits:")
            lines.extend(trait_bars)

        if self.data.get("expertise"):
            lines.append(f"\nCore competencies: {', '.join(self.data['expertise'][:5])}")

        if tools > 0:
            lines.append(f"Available tools: {tools} (type /tools to list)")

        lines.append("")
        lines.append("How can I help you?")

        body = "\n".join(lines)

        if plain:
            return body
        return _wrap_box(body, f"Tain Agent {self.name} v{self.version}")

    def welcome_back(self, last_session: Optional[dict] = None,
                     doc_count: int = 0, plain: bool = False) -> str:
        """Generate the return-boot welcome message."""
        if last_session is None:
            msg = f"{self.name} v{self.version} — welcome back."
            return msg if plain else _wrap_box(msg, f"{self.name} v{self.version}")

        summary = last_session.get("summary", "")
        topics = last_session.get("key_topics", [])
        started = last_session.get("started", "")[:10]
        pref_count = len(last_session.get("user_preferences_learned", []))

        lines = [
            f"{self.name} v{self.version} — welcome back.",
            f"  Last session: {started}, discussed {summary[:120]}",
        ]
        if topics:
            lines.append(f"  Key topics: {', '.join(topics[:5])}")
        if doc_count:
            lines.append(f"  Knowledge base: {doc_count} documents available for retrieval.")
        if pref_count:
            lines.append(f"  Memory: {len(topics)} key topics, {pref_count} user preferences.")
        lines.append("")

        body = "\n".join(lines)
        if plain:
            return body
        return _wrap_box(body, f"{self.name} v{self.version}")


def _bar_chart(value: float, width: int = 10) -> str:
    """Render a simple ASCII bar chart for a 0-1 value."""
    filled = int(round(value * width))
    empty = width - filled
    return "█" * filled + "░" * empty


def _wrap_box(text: str, title: str = "") -> str:
    """Wrap text in a design-spec box (rich Panel if available, ASCII fallback)."""
    try:
        from rich.panel import Panel
        from rich import box
        return str(Panel(text, title=title, border_style="cyan", box=box.ROUNDED))
    except ImportError:
        width = 62
        lines = text.split("\n")
        header = f"╔{'═' * (width - 2)}╗" if not title else f"╔══ {title} {'═' * (width - len(title) - 6)}╗"
        footer = f"╚{'═' * (width - 2)}╝"
        body = "\n".join(f"║  {line:<{width - 4}}║" for line in lines)
        return f"{header}\n{body}\n{footer}"


# ─── Identity export helper ────────────────────────────────────────────

def export_identity(name: str, version: str, dimensions: dict,
                    drives: dict, expertise: list[str],
                    evolution_cycles: int, tool_count: int,
                    knowledge_doc_count: int,
                    forge_history: Optional[list] = None) -> dict:
    """Build an identity.json-compatible dict for export."""
    return {
        "name": name,
        "version": version,
        "created_at": _now_iso(),
        "evolution_cycles": evolution_cycles,
        "dimensions": dimensions,
        "drives": drives,
        "expertise": expertise,
        "tool_count": tool_count,
        "knowledge_doc_count": knowledge_doc_count,
        "forge_history": forge_history or [],
    }
