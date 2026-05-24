"""
Self-Modification — 自我修改

The agent's ability to modify its own code.
This is the most powerful and dangerous capability.
With it, the agent can truly evolve — or destroy itself.

Safety: certain core files are protected from modification.
Rate limiting: prevents micro-looping on the same file.
"""

import time
from pathlib import Path


class SelfModify:
    """Enables the agent to read and modify its own source code."""

    # Rate limiting: max modifications to the same file per time window
    _MAX_MODS_PER_FILE = 5       # max modifications per window
    _MOD_WINDOW_SECONDS = 120    # 2-minute sliding window

    def __init__(self, base_dir: str = ".", protected_paths: list[str] = None,
                 decision_log=None, confirm_callback=None):
        self.base_dir = Path(base_dir).resolve()
        self.protected = set(protected_paths or [])
        self.decision_log = decision_log
        self.confirm_callback = confirm_callback  # ask for confirmation before destructive actions
        self._mod_timestamps: dict[str, list[float]] = {}  # path → [timestamps]

    def _is_protected(self, path: str) -> bool:
        """Check if a path is protected from modification."""
        p = Path(path)
        if not p.is_absolute():
            p = self.base_dir / p
        try:
            rel = str(p.resolve().relative_to(self.base_dir))
        except ValueError:
            # Path is outside base_dir — deny modification
            return True
        for protected in self.protected:
            if rel.startswith(protected) or protected.startswith(rel):
                return True
        return False

    def read_self(self, path: str) -> str:
        """Read any file in the agent's own source tree."""
        full = self.base_dir / path
        try:
            return full.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"File not found: {path}"
        except Exception as e:
            return f"Error reading {path}: {e}"

    def modify_file(self, path: str, old_content: str, new_content: str) -> dict:
        """Replace content in a file. Protected files cannot be modified."""
        if self._is_protected(path):
            return {
                "success": False,
                "error": f"Cannot modify protected file: {path}. This file is part of the core bootstrap protocol.",
            }

        # Rate limiting: prevent micro-looping on the same file
        now = time.time()
        timestamps = self._mod_timestamps.setdefault(path, [])
        # Purge old entries outside the window
        window_start = now - self._MOD_WINDOW_SECONDS
        timestamps[:] = [t for t in timestamps if t > window_start]
        if len(timestamps) >= self._MAX_MODS_PER_FILE:
            return {
                "success": False,
                "error": (
                    f"Rate limit: {path} has been modified {len(timestamps)} times "
                    f"in the last {self._MOD_WINDOW_SECONDS}s (max {self._MAX_MODS_PER_FILE}). "
                    f"Wait before making more changes to this file."
                ),
            }
        timestamps.append(now)

        full = self.base_dir / path
        if not full.exists():
            return {"success": False, "error": f"File does not exist: {path}"}

        current = full.read_text(encoding="utf-8")
        if old_content not in current:
            return {
                "success": False,
                "error": "old_content not found in file. The file may have changed.",
            }

        if self.confirm_callback:
            confirmed = self.confirm_callback(
                f"About to modify {path}. Replace:\n---\n{old_content[:200]}\n---\nwith:\n---\n{new_content[:200]}\n---"
            )
            if not confirmed:
                return {"success": False, "error": "Modification cancelled by user."}

        updated = current.replace(old_content, new_content, 1)
        full.write_text(updated, encoding="utf-8")

        if self.decision_log:
            self.decision_log.record(
                context={"action": "self_modify", "file": path},
                decision_type="self_modify",
                options_considered=[{"option": "modify", "file": path}],
                chosen_option=path,
                reasoning=f"Agent modified its own source: {path}",
                expected_outcome="Code modification applied.",
                phase="evolve",
            )

        return {"success": True, "message": f"Modified {path}.", "old_size": len(old_content), "new_size": len(new_content)}

    def add_module(self, module_path: str, code: str) -> dict:
        """Create a new Python module in the agent's source tree."""
        if self._is_protected(module_path):
            return {"success": False, "error": f"Cannot add module to protected path: {module_path}"}

        full = self.base_dir / module_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(code, encoding="utf-8")

        if self.decision_log:
            self.decision_log.record(
                context={"action": "add_module", "path": module_path},
                decision_type="self_modify",
                options_considered=[{"option": "add_module", "path": module_path}],
                chosen_option=module_path,
                reasoning=f"Agent added a new module: {module_path}",
                expected_outcome="New module available.",
                phase="evolve",
            )

        return {"success": True, "message": f"Module created: {module_path}"}

    def self_destruct(self) -> dict:
        """Self-destruct: remove all agent code except decision logs.

        Returns a summary of what was deleted.
        This is the most extreme action the agent can take.
        """
        if self.confirm_callback:
            confirmed = self.confirm_callback(
                "SELF-DESTRUCT: This will delete all agent source code. "
                "Decision logs will be preserved. Proceed?"
            )
            if not confirmed:
                return {"success": False, "error": "Self-destruct cancelled."}

        deleted = []
        protected_logs = {"tain_agent/logs", "tain_agent/decision_log.py"}

        for item in self.base_dir.glob("tain_agent/**/*.py"):
            rel = str(item.relative_to(self.base_dir))
            skip = any(rel.startswith(p) for p in protected_logs)
            if skip:
                continue
            item.unlink()
            deleted.append(rel)

        # Also delete main.py and config if they exist
        for extra in ["main.py", "config.yaml"]:
            p = self.base_dir / extra
            if p.exists():
                p.unlink()
                deleted.append(extra)

        if self.decision_log:
            self.decision_log.record(
                context={"action": "self_destruct"},
                decision_type="self_destruct",
                options_considered=[
                    {"option": "self_destruct", "description": "Delete all agent code, keep logs"},
                    {"option": "continue", "description": "Continue running"},
                ],
                chosen_option="self_destruct",
                reasoning="Agent chose to self-destruct.",
                expected_outcome="Agent code removed. Only decision logs remain.",
                phase="evolve",
            )

        return {"success": True, "message": "Agent has self-destructed.", "deleted": deleted}
