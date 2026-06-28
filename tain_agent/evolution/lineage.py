"""
Evolution Lineage — 演化血统追踪

Records the evolutionary history of every self-modification, tool forging,
and module addition. Creates an auditable "family tree" of the agent's growth.

Each lineage entry records:
  - event_type: forge_tool | self_modify | add_module
  - artifact: what was created/modified (tool name, file path)
  - agent_version: agent version at time of change
  - parent: what existed before (previous file hash or "none")
  - child: what was created (new file hash or tool metadata)
  - reasoning: why this change was made
  - timestamp: when

Storage: JSONL append-only file (same pattern as decision_log).

This enables:
  - "Who created this tool and why?"
  - "What chain of modifications led to this file?"
  - "Show me the full evolution tree."
"""

import json
import hashlib
from pathlib import Path
from tain_agent.core.time_utils import now
from typing import Optional


def _hash_file(filepath: Path) -> str:
    """Compute SHA-256 hash of a file's contents."""
    if not filepath.exists():
        return "none"
    return hashlib.sha256(filepath.read_bytes()).hexdigest()[:16]


class LineageTracker:
    """Tracks the evolutionary lineage of the agent's artifacts."""

    def __init__(self, lineage_path: Path):
        self.lineage_path = Path(lineage_path)
        self.lineage_path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[dict] = []
        self._load()

    def _load(self) -> None:
        """Load existing lineage entries."""
        if self.lineage_path.exists():
            try:
                for line in self.lineage_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        self._entries.append(json.loads(line))
            except (json.JSONDecodeError, IOError):
                pass

    def _append(self, entry: dict) -> None:
        """Append a lineage entry to the log."""
        entry["id"] = len(self._entries) + 1
        entry["timestamp"] = now().isoformat()
        self._entries.append(entry)
        with open(self.lineage_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def record_forge(self, tool_name: str, tool_code: str,
                     agent_version: str, reasoning: str = "") -> dict:
        """Record a tool forging event.

        Args:
            tool_name: Name of the forged tool.
            tool_code: The Python code of the tool.
            agent_version: Agent version at time of forging.
            reasoning: Why this tool was created.
        """
        # Hash the tool code for lineage
        code_hash = hashlib.sha256(tool_code.encode()).hexdigest()[:16]

        entry = {
            "event_type": "forge_tool",
            "artifact": tool_name,
            "artifact_type": "tool",
            "agent_version": agent_version,
            "parent": "none",
            "child": code_hash,
            "reasoning": reasoning,
        }
        self._append(entry)
        return entry

    def record_modify(self, filepath: str, old_content: str, new_content: str,
                      agent_version: str, reasoning: str = "",
                      base_dir: str = ".") -> dict:
        """Record a self-modification event.

        Args:
            filepath: Path to the modified file (relative to base_dir).
            old_content: Content before modification.
            new_content: Content after modification.
            agent_version: Agent version at time of modification.
            reasoning: Why this modification was made.
            base_dir: Root directory.
        """
        old_hash = hashlib.sha256(old_content.encode()).hexdigest()[:16]
        new_hash = hashlib.sha256(new_content.encode()).hexdigest()[:16]

        # Also hash the actual file on disk (post-modification verification)
        full_path = Path(base_dir) / filepath
        disk_hash = _hash_file(full_path)

        entry = {
            "event_type": "self_modify",
            "artifact": filepath,
            "artifact_type": "file",
            "agent_version": agent_version,
            "parent": old_hash,
            "child": new_hash,
            "disk_hash": disk_hash,
            "reasoning": reasoning,
        }
        self._append(entry)
        return entry

    def record_add_module(self, module_path: str, code: str,
                          agent_version: str, reasoning: str = "") -> dict:
        """Record a new module addition."""
        code_hash = hashlib.sha256(code.encode()).hexdigest()[:16]

        entry = {
            "event_type": "add_module",
            "artifact": module_path,
            "artifact_type": "module",
            "agent_version": agent_version,
            "parent": "none",
            "child": code_hash,
            "reasoning": reasoning,
        }
        self._append(entry)
        return entry

    def record_mutation(self, version: str, layer: str,
                        change_type: str, detail: str = "") -> dict:
        """Record a mutation event in the package lineage."""
        entry = {
            "event": "mutation",
            "version": version,
            "layer": layer,
            "change": change_type,
            "detail": detail,
        }
        self._append(entry)
        return entry

    def record_rollback(self, version: str, reason: str = "") -> dict:
        """Record a rollback event."""
        entry = {
            "event": "rollback",
            "version": version,
            "reason": reason,
        }
        self._append(entry)
        return entry

    # ── Query ──────────────────────────────────────────────────────

    def lineage_for(self, artifact: str) -> list[dict]:
        """Get the full lineage chain for a given artifact (tool name or file path).

        Returns all entries where this artifact was created or modified,
        ordered by time.
        """
        return [e for e in self._entries if e.get("artifact") == artifact]

    def all_tools(self) -> list[str]:
        """List all tools that have lineage records."""
        tools = set()
        for e in self._entries:
            if e.get("event_type") == "forge_tool" and e.get("artifact"):
                tools.add(e["artifact"])
        return sorted(tools)

    def all_files(self) -> list[str]:
        """List all files that have modification records."""
        files = set()
        for e in self._entries:
            if e.get("event_type") in ("self_modify", "add_module") and e.get("artifact"):
                files.add(e["artifact"])
        return sorted(files)

    def summary(self) -> dict:
        """Return a summary of the entire lineage."""
        forge_count = sum(1 for e in self._entries if e["event_type"] == "forge_tool")
        modify_count = sum(1 for e in self._entries if e["event_type"] == "self_modify")
        add_count = sum(1 for e in self._entries if e["event_type"] == "add_module")

        return {
            "total_events": len(self._entries),
            "forge_events": forge_count,
            "modify_events": modify_count,
            "add_module_events": add_count,
            "tools_created": self.all_tools(),
            "files_modified": self.all_files(),
            "lineage_file": str(self.lineage_path),
        }

    def export_tree(self, artifact: Optional[str] = None) -> str:
        """Export lineage as a human-readable tree.

        If artifact is specified, shows only that artifact's lineage.
        Otherwise shows all entries.
        """
        entries = self.lineage_for(artifact) if artifact else self._entries
        if not entries:
            return "No lineage entries found."

        lines = [f"Evolution Lineage ({len(entries)} entries):"]
        lines.append("=" * 60)
        for e in entries:
            event = e["event_type"]
            art = e["artifact"]
            ver = e.get("agent_version", "?")
            ts = e.get("timestamp", "?")[:19]
            reason = e.get("reasoning", "")[:80]
            parent = e.get("parent", "?")
            child = e.get("child", "?")

            if event == "forge_tool":
                icon = "🔧"
                action = f"FORGED {art}"
            elif event == "self_modify":
                icon = "✏️"
                action = f"MODIFIED {art}"
            elif event == "add_module":
                icon = "📦"
                action = f"ADDED {art}"
            else:
                icon = "❓"
                action = f"{event} {art}"

            lines.append(f"  {icon} [{ts}] v{ver} {action}")
            lines.append(f"     {parent} → {child}")
            if reason:
                lines.append(f"     原因: {reason}")

        return "\n".join(lines)

    def count(self) -> int:
        """Return the total number of lineage entries."""
        return len(self._entries)
