"""Shared data access for Web UI — reads from agent_workspace/ filesystem."""

import json
import os
import time
from pathlib import Path
from typing import Any

from tain_agent import __version__

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = PROJECT_ROOT / "agent_workspace"
PID_DIR = WORKSPACE_ROOT  # .agent_daemon_{name}.pid files live here

# Simple TTL cache for knowledge file listings
_knowledge_cache: dict[str, tuple[float, list[dict]]] = {}
_KNOWLEDGE_CACHE_TTL = 10  # seconds


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError, FileNotFoundError):
        return None


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    try:
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except IOError:
        pass
    return entries


def is_agent_running(name: str) -> bool:
    pid_path = PID_DIR / f".agent_daemon_{name}.pid"
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, OSError):
        return False


def get_registry() -> dict:
    path = WORKSPACE_ROOT / "_registry.json"
    return _read_json(path) or {"agents": {}}


def list_agents() -> list[dict]:
    registry = get_registry()
    agents = []
    for name, info in registry.get("agents", {}).items():
        running = is_agent_running(name)
        version = _read_json(WORKSPACE_ROOT / name / "version.json")
        personality = _read_json(WORKSPACE_ROOT / name / "state" / "personality.json")
        memory = _read_json(WORKSPACE_ROOT / name / "logs" / "memory.json")

        # Count forged tools
        forged_dir = WORKSPACE_ROOT / name / "forged_tools"
        tool_count = len(list(forged_dir.glob("*.meta.json"))) if forged_dir.exists() else 0

        # Count decisions
        decisions = _read_jsonl(WORKSPACE_ROOT / name / "logs" / "decisions.jsonl")
        decision_count = len(decisions)

        # Count lineage events
        lineage = _read_jsonl(WORKSPACE_ROOT / name / "logs" / "lineage.jsonl")
        lineage_count = len(lineage)

        # Count knowledge files
        knowledge_dir = WORKSPACE_ROOT / name / "knowledge"
        files_dir = WORKSPACE_ROOT / name / "files"
        knowledge_count = 0
        if knowledge_dir.exists():
            knowledge_count += len(list(knowledge_dir.rglob("*")))
        if files_dir.exists():
            knowledge_count += len(list(files_dir.rglob("*")))

        # Extract phase and cycle from memory
        phase = "unknown"
        cycle_count = 0
        goal_count = 0
        if memory:
            phase_data = memory.get("agent_phase", {})
            phase = phase_data.get("value", "unknown") if isinstance(phase_data, dict) else "unknown"
            goals_data = memory.get("goals", {})
            if isinstance(goals_data, dict):
                goals = goals_data.get("value", {})
                goal_count = len(goals) if isinstance(goals, dict) else 0
            cycle_data = memory.get("cycle_count", {})
            if isinstance(cycle_data, dict):
                cycle_count = cycle_data.get("value", 0)

        # Conversation message count
        conv_messages = 0
        conv_jsonl = WORKSPACE_ROOT / name / "logs" / "conversations" / "web_user.jsonl"
        if conv_jsonl.exists():
            conv_messages = len(_read_jsonl(conv_jsonl))

        agents.append({
            "name": name,
            "role": info.get("role"),
            "evolution_mode": info.get("evolution_mode", "chaos"),
            "version": version.get("version", info.get("framework_version", __version__)) if version else info.get("framework_version", __version__),
            "status": "running" if running else "stopped",
            "phase": phase,
            "cycle_count": cycle_count,
            "tool_count": tool_count,
            "decision_count": decision_count,
            "lineage_count": lineage_count,
            "knowledge_count": knowledge_count,
            "goal_count": goal_count,
            "conv_messages": conv_messages,
            "created_at": info.get("created_at", ""),
            "last_active_at": info.get("last_active_at", ""),
        })
    return agents


def get_agent(name: str) -> dict | None:
    agents = list_agents()
    for a in agents:
        if a["name"] == name:
            return a
    return None


def get_agent_decisions(name: str, phase: str = "", decision_type: str = "",
                        limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
    entries = _read_jsonl(WORKSPACE_ROOT / name / "logs" / "decisions.jsonl")
    if phase:
        entries = [e for e in entries if e.get("phase") == phase]
    if decision_type:
        entries = [e for e in entries if e.get("decision_type") == decision_type]
    total = len(entries)
    return entries[offset:offset + limit], total


def get_agent_tools(name: str) -> list[dict]:
    forged_dir = WORKSPACE_ROOT / name / "forged_tools"
    if not forged_dir.exists():
        return []
    tools = []
    for meta_file in sorted(forged_dir.glob("*.meta.json")):
        meta = _read_json(meta_file)
        if not meta:
            continue
        tool_name = meta.get("name", meta_file.stem)
        source_file = forged_dir / f"{tool_name}.py"
        source = source_file.read_text(encoding="utf-8") if source_file.exists() else ""
        tools.append({
            "name": tool_name,
            "description": meta.get("description", ""),
            "parameters": meta.get("parameters", {}),
            "source": source,
        })
    return tools


def get_agent_tool_detail(name: str, tool_name: str) -> dict | None:
    meta = _read_json(WORKSPACE_ROOT / name / "forged_tools" / f"{tool_name}.meta.json")
    if not meta:
        return None
    source_file = WORKSPACE_ROOT / name / "forged_tools" / f"{tool_name}.py"
    source = source_file.read_text(encoding="utf-8") if source_file.exists() else ""
    return {
        "name": tool_name,
        "description": meta.get("description", ""),
        "parameters": meta.get("parameters", {}),
        "source": source,
    }


def get_agent_evolution(name: str) -> list[dict]:
    return _read_jsonl(WORKSPACE_ROOT / name / "logs" / "lineage.jsonl")


def get_agent_metrics(name: str) -> list[dict]:
    metrics_dir = WORKSPACE_ROOT / name / "state" / "metrics_snapshots"
    if not metrics_dir.exists():
        return []
    metrics = []
    for f in sorted(metrics_dir.glob("metrics_*.json")):
        data = _read_json(f)
        if data:
            metrics.append(data)
    return metrics


def get_agent_personality(name: str) -> dict | None:
    return _read_json(WORKSPACE_ROOT / name / "state" / "personality.json")


def get_agent_knowledge(name: str) -> list[dict]:
    now = time.monotonic()
    cached = _knowledge_cache.get(name)
    if cached and (now - cached[0]) < _KNOWLEDGE_CACHE_TTL:
        return cached[1]

    entries = []
    for subdir in ("knowledge", "files", "poetry", "journal", "commitments"):
        d = WORKSPACE_ROOT / name / subdir
        if not d.exists():
            continue
        for f in sorted(d.rglob("*")):
            if f.is_file():
                try:
                    size = f.stat().st_size
                except OSError:
                    size = 0
                entries.append({
                    "path": str(f.relative_to(WORKSPACE_ROOT / name)),
                    "name": f.name,
                    "directory": subdir,
                    "size": size,
                })
    _knowledge_cache[name] = (now, entries)
    return entries


def get_agent_knowledge_content(name: str, rel_path: str) -> tuple[str, str]:
    full_path = (WORKSPACE_ROOT / name / rel_path).resolve()
    allowed_root = (WORKSPACE_ROOT / name).resolve()
    if not str(full_path).startswith(str(allowed_root) + "/") and full_path != allowed_root:
        return "", "Access denied."
    if not full_path.exists():
        return "", "File not found."
    try:
        content = full_path.read_text(encoding="utf-8")
    except (IOError, UnicodeDecodeError):
        return "", "Cannot read file (binary or encoding error)."
    suffix = full_path.suffix.lower()
    if suffix in (".md", ".markdown"):
        return "markdown", content
    elif suffix == ".json":
        try:
            parsed = json.loads(content)
            return "json", json.dumps(parsed, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return "text", content
    return "text", content


def get_agent_goals(name: str) -> list[dict]:
    memory = _read_json(WORKSPACE_ROOT / name / "logs" / "memory.json")
    if not memory:
        return []
    goals_data = memory.get("goals", {})
    if isinstance(goals_data, dict):
        goals = goals_data.get("value", {})
        if isinstance(goals, dict):
            return list(goals.values())
    return []


def get_config() -> dict:
    config_path = PROJECT_ROOT / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}
