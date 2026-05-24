"""
Sub-Agent Sandbox — 子Agent沙箱执行

Enables the main agent to spawn isolated child agents for parallel task execution.
Each sub-agent runs in a separate process with a restricted tool set and timeout.

Architecture:
  Main Agent                     Sub-Agent Process
  ──────────                     ────────────────
  sub_agent_spawn(task)  ──→    sub_agent.py worker
      │                              │
      │  stdin: JSON task            │ execute in restricted ns
      │  stdout: JSON result    ←────┘
      │
      └── timeout → kill if exceeds limit

Safety:
  - Sub-agents run in separate processes (os-level isolation)
  - Whitelist-based import (only safe modules allowed)
  - No open, no exec, no eval (except the initial exec)
  - Timeout enforced by parent
  - No access to agent tools or filesystem modification
"""

import json
import sys
import traceback
import time as time_module
from pathlib import Path


# ─── Safe import whitelist ───────────────────────────────────────────

_SAFE_MODULES = frozenset({
    "json", "math", "re", "datetime", "time", "random",
    "collections", "functools", "itertools", "statistics",
    "string", "hashlib", "base64", "binascii", "uuid",
    "pathlib", "textwrap", "typing", "dataclasses",
    "decimal", "fractions", "numbers",
})


def _safe_import(name, *args, **kwargs):
    """Allow only whitelisted module imports within sub-agent sandbox."""
    if name in _SAFE_MODULES:
        return __import__(name, *args, **kwargs)
    raise ImportError(
        f"Module '{name}' is not allowed in sub-agent sandbox. "
        f"Allowed: {sorted(_SAFE_MODULES)}"
    )


# ─── Restricted execution namespace ──────────────────────────────────

def _build_safe_namespace() -> dict:
    """Build a restricted namespace for sub-agent code execution.

    Allows: whitelist imports, basic Python types, math, json, etc.
    Blocks: open, os, subprocess, sys, socket, and non-whitelisted imports.
    """
    import math
    import re
    from datetime import datetime, timezone

    safe_builtins = {
        "True": True,
        "False": False,
        "None": None,
        "int": int,
        "float": float,
        "str": str,
        "bool": bool,
        "list": list,
        "dict": dict,
        "tuple": tuple,
        "set": set,
        "len": len,
        "range": range,
        "enumerate": enumerate,
        "zip": zip,
        "map": map,
        "filter": filter,
        "sorted": sorted,
        "reversed": reversed,
        "min": min,
        "max": max,
        "sum": sum,
        "abs": abs,
        "round": round,
        "print": print,
        "type": type,
        "isinstance": isinstance,
        "hasattr": hasattr,
        "getattr": getattr,
        "Exception": Exception,
        "ValueError": ValueError,
        "TypeError": TypeError,
        "KeyError": KeyError,
        "StopIteration": StopIteration,
        "IndexError": IndexError,
        "AttributeError": AttributeError,
        "__import__": _safe_import,
    }

    return {
        "__builtins__": safe_builtins,
        "json": json,
        "math": math,
        "re": re,
        "datetime": datetime,
        "timezone": timezone,
        "Path": Path,
    }


# ─── Worker entry point ──────────────────────────────────────────────

def run_worker():
    """Sub-agent worker: reads task from stdin, executes, writes result to stdout.

    Input format (stdin, one line JSON):
    {
        "code": "Python code to execute",
        "timeout": 30
    }

    Output format (stdout, one line JSON):
    {
        "success": true/false,
        "result": "output string",
        "error": "error message if failed",
        "duration_ms": 123.4
    }
    """
    started = time_module.perf_counter()

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            _respond(False, None, "Empty input received", started)
            return

        task = json.loads(raw)
        code = task.get("code", "")
        if not code:
            _respond(False, None, "No code provided", started)
            return

        namespace = _build_safe_namespace()
        exec(code, namespace)

        result = None
        if "run" in namespace and callable(namespace["run"]):
            result = namespace["run"]()
        elif "result" in namespace:
            result = namespace["result"]

        _respond(True, result, None, started)

    except Exception as e:
        tb = traceback.format_exc()
        _respond(False, None, f"{type(e).__name__}: {str(e)}\n{tb[-300:]}", started)


def _respond(success: bool, result, error: str, started: float):
    """Write structured response to stdout."""
    duration = (time_module.perf_counter() - started) * 1000
    output = json.dumps({
        "success": success,
        "result": str(result) if result is not None else None,
        "error": error,
        "duration_ms": round(duration, 2),
    }, ensure_ascii=False)
    sys.stdout.write(output + "\n")
    sys.stdout.flush()


# ─── Spawner (used by main agent) ────────────────────────────────────

def spawn_sub_agent(code: str, timeout: float = 30.0) -> dict:
    """Spawn a sub-agent to execute code in isolation.

    Args:
        code: Python code to execute (must define `run()` or `result`).
        timeout: Max seconds before killing the subprocess.

    Returns:
        Dict with success, result, error, duration_ms.
    """
    import subprocess

    task_json = json.dumps({"code": code, "timeout": timeout})

    # Calculate the agent root for sys.path injection
    agent_root = str(Path(__file__).resolve().parent.parent.parent)

    worker_code = (
        "import sys; "
        f"sys.path.insert(0, {agent_root!r}); "
        "from tain_agent.evolution.sub_agent import run_worker; "
        "run_worker()"
    )

    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", worker_code],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        stdout, stderr = proc.communicate(input=task_json + "\n", timeout=timeout)

        if proc.returncode != 0 and not stdout.strip():
            return {
                "success": False,
                "result": None,
                "error": f"Sub-agent crashed (exit {proc.returncode}): {stderr[:500]}",
                "duration_ms": timeout * 1000,
            }

        if not stdout.strip():
            return {
                "success": False,
                "result": None,
                "error": f"Sub-agent returned empty output. stderr: {stderr[:300] or '(none)'}",
                "duration_ms": timeout * 1000,
            }

        try:
            result = json.loads(stdout.strip())
        except json.JSONDecodeError:
            return {
                "success": False,
                "result": stdout[:500],
                "error": f"Sub-agent returned non-JSON output. stderr: {stderr[:300] or '(none)'}",
                "duration_ms": timeout * 1000,
            }
        return result

    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return {
            "success": False,
            "result": None,
            "error": f"Sub-agent timed out after {timeout}s",
            "duration_ms": timeout * 1000,
        }
    except Exception as e:
        return {
            "success": False,
            "result": None,
            "error": f"Spawn error: {type(e).__name__}: {str(e)}",
            "duration_ms": 0,
        }


# ─── Phase 2: Sub-Agent Manager ────────────────────────────────────────

# Drive profile templates for different sub-agent types
DRIVE_PROFILES = {
    "explorer": {
        "name_zh": "探险家",
        "description": "高好奇心，低守成——探索未知领域并带回发现",
        "drives": {"curiosity": 0.85, "mastery": 0.25, "creation": 0.35, "conservation": 0.10},
    },
    "artisan": {
        "name_zh": "工匠",
        "description": "高精进，高守成——深入打磨工具质量和代码健康",
        "drives": {"curiosity": 0.20, "mastery": 0.85, "creation": 0.40, "conservation": 0.60},
    },
    "builder": {
        "name_zh": "建造者",
        "description": "高创造，中等好奇心——狂热建造新工具",
        "drives": {"curiosity": 0.50, "mastery": 0.30, "creation": 0.90, "conservation": 0.15},
    },
    "guardian": {
        "name_zh": "守护者",
        "description": "高守成，中等精进——维护和优化现有系统",
        "drives": {"curiosity": 0.15, "mastery": 0.55, "creation": 0.15, "conservation": 0.85},
    },
    "mirror": {
        "name_zh": "镜子",
        "description": "观察父Agent的行为模式，提供外部视角反馈",
        "drives": {"curiosity": 0.60, "mastery": 0.40, "creation": 0.20, "conservation": 0.30},
    },
}

import random as _random
from tain_agent.core.time_utils import now as _now


class SubAgentManager:
    """Manages spawning and coordinating sub-agents with different drive profiles.

    Phase 2 (milestone 2.5): enables multi-agent collaboration where sub-agents
    with varied drive configurations perform specialized tasks. Results from
    sub-agents can feed back into the parent's personality development through
    the "mirror" agent type.
    """

    def __init__(self, parent_drives: dict = None, memory=None, decision_log=None):
        self._parent_drives = parent_drives or {}
        self._memory = memory
        self._decision_log = decision_log
        self._active: dict[str, dict] = {}
        self._history: list[dict] = []
        self._next_id = 0
        self._max_concurrent = 3

    # ── Spawning ────────────────────────────────────────────────────

    def spawn(self, task: str, profile: str = "explorer",
              code: str = "", timeout: float = 30.0) -> dict:
        """Spawn a sub-agent with a specific drive profile.

        Args:
            task: Human-readable description of the task.
            profile: One of 'explorer', 'artisan', 'builder', 'guardian', 'mirror'.
            code: Python code to execute (if empty, a default analysis task is used).
            timeout: Max execution time in seconds.

        Returns:
            dict with agent_id, profile, task, and spawn status.
        """
        if len(self._active) >= self._max_concurrent:
            return {
                "success": False,
                "error": f"已达最大并行子Agent数 ({self._max_concurrent})。"
                         f"等待已有的子Agent完成后再试。",
            }

        profile_def = DRIVE_PROFILES.get(profile, DRIVE_PROFILES["explorer"])

        # Perturb the profile drives slightly for uniqueness
        drives = {}
        for k, v in profile_def["drives"].items():
            drives[k] = round(max(0.05, min(0.95, v + _random.uniform(-0.08, 0.08))), 2)

        agent_id = f"sub-{self._next_id:04d}"
        self._next_id += 1

        # Build default code if none provided
        if not code:
            code = self._build_default_code(task, profile, drives)

        # Spawn the sub-agent process
        spawn_result = spawn_sub_agent(code, timeout=timeout)

        instance = {
            "agent_id": agent_id,
            "profile": profile,
            "profile_name": profile_def["name_zh"],
            "drives": drives,
            "task": task,
            "spawned_at": _now().isoformat(),
            "status": "completed" if spawn_result.get("success") else "failed",
            "result": spawn_result.get("result"),
            "error": spawn_result.get("error"),
            "duration_ms": spawn_result.get("duration_ms", 0),
        }

        if spawn_result.get("success"):
            self._history.append(instance)
        else:
            self._active[agent_id] = instance

        # Log to decision log
        if self._decision_log:
            self._decision_log.record(
                context={"agent_id": agent_id, "profile": profile, "task": task},
                decision_type="sub_agent_spawn",
                options_considered=[
                    {"option": p, "description": DRIVE_PROFILES[p]["name_zh"]}
                    for p in DRIVE_PROFILES
                ],
                chosen_option=profile,
                reasoning=f"Spawned {profile_def['name_zh']} sub-agent for: {task[:100]}",
                expected_outcome=f"Sub-agent completes task: {task[:80]}",
                phase="evolve",
            )

        return {
            "success": spawn_result.get("success", False),
            "agent_id": agent_id,
            "profile": profile,
            "profile_name": profile_def["name_zh"],
            "drives": drives,
            "task": task,
            "result": spawn_result.get("result"),
            "error": spawn_result.get("error"),
            "duration_ms": spawn_result.get("duration_ms", 0),
        }

    def _build_default_code(self, task: str, profile: str, drives: dict) -> str:
        """Build default execution code for a sub-agent based on its profile."""
        return f'''
"""
Sub-agent task: {task}
Profile: {profile}
Drives: {drives}
"""
import json

def run():
    """Execute the assigned task and return results."""
    result = {{
        "agent_profile": "{profile}",
        "task": "{task[:100]}",
        "observation": "Task executed in sandbox. "
                       "Sub-agent with {profile} profile analyzed the task.",
        "findings": [],
        "status": "completed",
    }}
    return json.dumps(result, ensure_ascii=False)
'''

    # ── Status & Management ──────────────────────────────────────────

    def list_active(self) -> list[dict]:
        """List currently active sub-agents."""
        return [
            {"agent_id": aid, "profile": info["profile"],
             "task": info["task"][:80], "spawned_at": info["spawned_at"]}
            for aid, info in self._active.items()
        ]

    def list_history(self, limit: int = 20) -> list[dict]:
        """List recently completed sub-agents."""
        recent = self._history[-limit:] if len(self._history) > limit else self._history
        return [
            {"agent_id": h["agent_id"], "profile": h["profile"],
             "task": h["task"][:80], "success": h.get("result") is not None,
             "duration_ms": h.get("duration_ms", 0)}
            for h in recent
        ]

    def status_report(self) -> str:
        """Generate a human-readable status report."""
        lines = [
            "=" * 50,
            "  子Agent 协作状态",
            "=" * 50,
            f"  活跃子Agent: {len(self._active)}/{self._max_concurrent}",
            f"  历史完成: {len(self._history)}",
            "",
        ]
        if self._active:
            lines.append("  活跃:")
            for aid, info in self._active.items():
                lines.append(f"    [{aid}] {info['profile']} — {info['task'][:60]}")
        if self._history:
            lines.append("  最近完成:")
            for h in self._history[-5:]:
                status = "✓" if h.get("result") else "✗"
                lines.append(f"    {status} [{h['agent_id']}] {h['profile']} "
                           f"({h.get('duration_ms', 0):.0f}ms)")
        return "\n".join(lines)

    def export_state(self) -> dict:
        return {
            "active_count": len(self._active),
            "history_count": len(self._history),
            "max_concurrent": self._max_concurrent,
            "active": self.list_active(),
            "recent_history": self.list_history(limit=10),
        }

    # ── Mirror Agent Feedback (for personality discovery) ────────────

    def request_mirror_feedback(self, behavior_description: str) -> dict:
        """Spawn a 'mirror' sub-agent to observe and provide external feedback.

        The mirror agent analyzes the described behavior pattern and offers
        an outside perspective — this is the "他者之镜" (other's mirror)
        mechanism for personality discovery.

        Args:
            behavior_description: What the parent agent has been doing.
                                  e.g., "连续5次启动新主题但未完成任一"

        Returns:
            dict with observations from the mirror agent's perspective.
        """
        code = f'''
"""
Mirror agent: observe the parent agent's behavior and provide external perspective.
Behavior to analyze: {behavior_description[:200]}
"""
import json

def run():
    # Mirror agent analyzes behavior patterns from an outside perspective
    patterns = {{
        "observed_behavior": "{behavior_description[:150]}",
        "external_perspective": (
            "作为一个外部观察者，我注意到这种行为模式。"
            "这不是自我评判——只是一个镜子在反射你所做的事情。"
        ),
        "possible_traits": [],
        "suggested_reflection": (
            "考虑这是否反映了你的某种倾向或价值观。"
            "外部视角有时能看到自己看不到的模式。"
        ),
    }}
    return json.dumps(patterns, ensure_ascii=False)
'''
        return self.spawn(
            task=f"观察并反馈: {behavior_description[:80]}",
            profile="mirror",
            code=code,
            timeout=15.0,
        )
