"""
Decision Log — 抉择日志系统

Every decision the Tao Agent makes is recorded here with full context,
options considered, reasoning, and outcome.

Format: JSONL (one JSON object per line) for append-only durability.
"""

import json
import uuid
from tain_agent.core.time_utils import now
from pathlib import Path
from typing import Optional

_MAX_CODE_LEN = 200  # max characters for code fields in decision log
_MAX_STR_LEN = 500   # default max for string fields


def _truncate_str(s: str, max_len: int = _MAX_STR_LEN) -> str:
    """Truncate a string if it exceeds max_len."""
    if len(s) <= max_len:
        return s
    return s[:max_len] + f"... [truncated, {len(s)} total chars]"


def _truncate_options(options: list[dict]) -> list[dict]:
    """Truncate code/input fields in options to prevent log bloat."""
    if not options:
        return options
    result = []
    for opt in options:
        truncated = dict(opt)
        for key in ("code", "input", "new_content", "old_content", "content"):
            if key in truncated and isinstance(truncated[key], str):
                truncated[key] = _truncate_str(truncated[key], _MAX_CODE_LEN)
        # Recurse into nested dicts
        for key, val in truncated.items():
            if isinstance(val, dict) and "code" in val:
                truncated[key] = _truncate_options([val])[0]
        result.append(truncated)
    return result


class DecisionLog:
    """Immutable append-only log of every decision the agent makes."""

    def __init__(self, log_dir: str = "tain_agent/logs", log_file: str = "decisions.jsonl"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / log_file

    def record(
        self,
        context: dict,
        decision_type: str,
        options_considered: list[dict],
        chosen_option: str,
        reasoning: str,
        expected_outcome: str,
        phase: str,
        actual_outcome: Optional[str] = None,
    ) -> str:
        """Record a decision to the immutable log. Returns the decision ID."""
        decision_id = str(uuid.uuid4())[:8]
        # Truncate large fields to prevent log bloat
        options_considered = _truncate_options(options_considered)
        reasoning = _truncate_str(reasoning, 500)
        expected_outcome = _truncate_str(expected_outcome, 300)
        entry = {
            "id": decision_id,
            "timestamp": now().isoformat(),
            "phase": phase,
            "context": context,
            "decision_type": decision_type,
            "options_considered": options_considered,
            "chosen_option": chosen_option,
            "reasoning": reasoning,
            "expected_outcome": expected_outcome,
            "actual_outcome": actual_outcome,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return decision_id

    def update_outcome(self, decision_id: str, actual_outcome: str) -> None:
        """Update a previous decision with its actual outcome (rewrites the line)."""
        if not self.log_path.exists():
            return
        lines = []
        with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue  # skip corrupted lines
                if entry.get("id") == decision_id:
                    entry["actual_outcome"] = actual_outcome
                lines.append(json.dumps(entry, ensure_ascii=False))
        with open(self.log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def read_all(self) -> list[dict]:
        """Read all decision entries."""
        if not self.log_path.exists():
            return []
        entries = []
        with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if isinstance(entry, dict) and "id" in entry:
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue  # skip corrupted lines
        return entries

    def filter_by_phase(self, phase: str) -> list[dict]:
        """Filter decisions by agent phase."""
        return [e for e in self.read_all() if e.get("phase") == phase]

    def summarize(self) -> str:
        """Return a human-readable summary of all decisions."""
        entries = self.read_all()
        if not entries:
            return "No decisions recorded yet."
        lines = [f"=== Decision Log Summary ({len(entries)} entries) ==="]
        for e in entries:
            eid = e.get("id", "????")
            ephase = e.get("phase", "?")
            etype = e.get("decision_type", "?")
            echoice = e.get("chosen_option", e.get("chosen", "?"))
            ereason = (e.get("reasoning", "") or "")[:100]
            lines.append(
                f"[{eid}] {ephase}/{etype}: "
                f"chose '{echoice}' — {ereason}"
            )
        return "\n".join(lines)
