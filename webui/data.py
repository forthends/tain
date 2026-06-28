"""Shared data access for Web UI — reads from agent_workspace/ filesystem."""

import json
import os
import time
from pathlib import Path
from typing import Any

from tain_agent import __version__

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = PROJECT_ROOT / "agent_workspace"
# New-package-format agents live under packages/ subdirectory.
PACKAGES_ROOT = WORKSPACE_ROOT / "packages"
PID_DIR = WORKSPACE_ROOT  # .agent_daemon_{name}.pid files live here

# Simple TTL cache for knowledge file listings
_knowledge_cache: dict[str, tuple[float, list[dict]]] = {}
_KNOWLEDGE_CACHE_TTL = 10  # seconds

# webui/data.py — Package-based data layer
from tain_agent.package import PackageRegistry, PackageKind
from tain_agent.package.manifest import parse_manifest

_registry = PackageRegistry(packages_root=PACKAGES_ROOT)


def list_agents_v2() -> list[dict]:
    """List agents from the new package-based system."""
    agents = []
    for pkg in _registry.list_packages(kind=PackageKind.AGENT):
        manifest = _registry.get_manifest(pkg.name)
        if manifest is None:
            continue
        agents.append({
            "name": pkg.name,
            "version": pkg.version,
            "kind": manifest.package.kind,
            "evolution_mode": manifest.package.evolution_mode,
            "tool_count": len(manifest.capability.tools),
            "artifact_count": len(manifest.expression.artifacts),
            "created_at": manifest.package.created_at,
            "updated_at": manifest.package.updated_at,
        })
    return agents


def get_agent_v2(name: str) -> dict | None:
    """Get a single agent from the package system."""
    manifest = _registry.get_manifest(name)
    if manifest is None:
        return None
    pkg = _registry.get_package(name)
    if pkg is None:
        return None
    return {
        "name": name,
        "version": pkg.version,
        "kind": manifest.package.kind,
        "evolution_mode": manifest.package.evolution_mode,
        "tool_count": len(manifest.capability.tools),
        "artifact_count": len(manifest.expression.artifacts),
        "created_at": manifest.package.created_at,
        "updated_at": manifest.package.updated_at,
    }


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


def _agent_path(name: str) -> Path:
    """Return the agent's package directory."""
    return PACKAGES_ROOT / name


def _agent_file(name: str, rel: str, _old_rel: str = "") -> Path:
    """Resolve a file path within the agent's package directory."""
    return _agent_path(name) / rel


def _agent_dir(name: str, rel: str, _old_rel: str = "") -> Path:
    """Resolve a directory path within the agent's package directory."""
    return _agent_path(name) / rel


def list_agents() -> list[dict]:
    registry = get_registry()
    agents = []
    for name, info in registry.get("agents", {}).items():
        running = is_agent_running(name)
        agent_dir = _agent_path(name)

        manifest = _read_json(agent_dir / "manifest.json")
        version = manifest.get("package", {}) if manifest else {}

        personality = _read_json(agent_dir / "cognitive" / "identity" / "profile.json")
        memory = _read_json(agent_dir / "_runtime" / "state" / "pral_phase.json")

        # Count forged tools
        forged_dir = agent_dir / "capability" / "tools"
        tool_count = len(list(forged_dir.glob("*.meta.json"))) if forged_dir.exists() else 0

        # Count decisions
        decisions = _read_jsonl(agent_dir / "cognitive" / "decisions.jsonl")
        decision_count = len(decisions)

        # Count lineage events
        lineage = _read_jsonl(agent_dir / "expression" / "lineage.jsonl")
        lineage_count = len(lineage)

        # Count knowledge files — reuse the TTL-cached listing to avoid
        # expensive recursive directory walks on every dashboard load.
        knowledge_count = len(get_agent_knowledge(name))

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
        conv_jsonl = agent_dir / "_runtime" / "conversations" / "web_user.jsonl"
        if not conv_jsonl.exists():
            conv_jsonl = agent_dir / "logs" / "conversations" / "web_user.jsonl"
        conv_messages = 0
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
    """Stream decisions from JSONL, keeping only the requested slice in memory.

    Avoids loading the entire file for agents with large decision logs.
    """
    path = _agent_file(name, "cognitive/decisions.jsonl", "logs/decisions.jsonl")
    if not path.exists():
        return [], 0

    matching: list[dict] = []
    total = 0
    end = offset + limit

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if phase and entry.get("phase") != phase:
                    continue
                if decision_type and entry.get("decision_type") != decision_type:
                    continue

                if total >= offset and total < end:
                    matching.append(entry)

                total += 1
    except IOError:
        pass

    return matching, total


def _normalize_params(params):
    """Normalize tool parameters to JSON Schema form: {'type':'object','properties':{...},'required':[...]}."""
    if not params:
        return {}
    if isinstance(params, list):
        props = {}
        required = []
        for p in params:
            if isinstance(p, dict) and "name" in p:
                pn = p["name"]
                props[pn] = {k: v for k, v in p.items() if k != "name"}
                if p.get("required"):
                    required.append(pn)
        return {"type": "object", "properties": props, "required": required}
    if isinstance(params, dict) and "properties" not in params:
        props = {}
        required = []
        for pname, pinfo in params.items():
            if isinstance(pinfo, dict):
                props[pname] = {k: v for k, v in pinfo.items() if k != "required"}
                if pinfo.get("required"):
                    required.append(pname)
        return {"type": "object", "properties": props, "required": required}
    return params


def _meta_stem(path: Path) -> str:
    """Return the filename stem, stripping both .meta and .json suffixes."""
    name = path.name
    if name.endswith(".meta.json"):
        return name[:-len(".meta.json")]
    return path.stem


def get_agent_tools(name: str) -> list[dict]:
    forged_dir = _agent_dir(name, "capability/tools", "forged_tools")
    if not forged_dir.exists():
        return []
    tools = []
    for meta_file in sorted(forged_dir.glob("*.meta.json")):
        meta = _read_json(meta_file)
        if not meta:
            continue
        tool_name = meta.get("name") or meta.get("tool_name") or _meta_stem(meta_file)
        source_file = forged_dir / f"{tool_name}.py"
        source = source_file.read_text(encoding="utf-8") if source_file.exists() else ""
        tools.append({
            "name": tool_name,
            "description": meta.get("description") or "",
            "parameters": _normalize_params(meta.get("parameters")),
            "source": source,
        })
    return tools


def get_agent_tool_detail(name: str, tool_name: str) -> dict | None:
    forged_dir = _agent_dir(name, "capability/tools", "forged_tools")
    meta = _read_json(forged_dir / f"{tool_name}.meta.json")
    if not meta:
        return None
    source_file = forged_dir / f"{tool_name}.py"
    source = source_file.read_text(encoding="utf-8") if source_file.exists() else ""
    return {
        "name": tool_name,
        "description": meta.get("description") or "",
        "parameters": _normalize_params(meta.get("parameters")),
        "source": source,
    }


def get_agent_evolution(name: str) -> list[dict]:
    lineage_path = _agent_file(name, "expression/lineage.jsonl", "logs/lineage.jsonl")
    return _read_jsonl(lineage_path)


def get_agent_metrics(name: str) -> list[dict]:
    metrics_dir = _agent_dir(name, "state/metrics_snapshots", "state/metrics_snapshots")
    if not metrics_dir.exists():
        return []
    metrics = []
    for f in sorted(metrics_dir.glob("metrics_*.json")):
        data = _read_json(f)
        if data:
            metrics.append(data)
    return metrics


def get_agent_personality(name: str) -> dict | None:
    return _read_json(_agent_file(name, "cognitive/identity/profile.json", "state/personality.json"))


def get_agent_knowledge(name: str) -> list[dict]:
    now = time.monotonic()
    cached = _knowledge_cache.get(name)
    if cached and (now - cached[0]) < _KNOWLEDGE_CACHE_TTL:
        return cached[1]

    agent_root = _agent_path(name)
    entries = []
    for subdir in ("knowledge", "files", "poetry", "journal", "commitments"):
        d = agent_root / subdir
        if not d.exists():
            # Try new package layout paths
            if subdir == "knowledge":
                d = agent_root / "cognitive" / "knowledge"
            elif subdir in ("poetry", "journal", "commitments"):
                d = agent_root / "expression" / "artifacts" / subdir
            elif subdir == "files":
                d = agent_root / "expression" / "artifacts"
        if not d.exists():
            continue
        for f in sorted(d.rglob("*")):
            if f.is_file():
                try:
                    size = f.stat().st_size
                except OSError:
                    size = 0
                entries.append({
                    "path": str(f.relative_to(agent_root)),
                    "name": f.name,
                    "directory": subdir,
                    "size": size,
                })
    _knowledge_cache[name] = (now, entries)
    return entries


def get_agent_knowledge_content(name: str, rel_path: str) -> tuple[str, str]:
    agent_root = _agent_path(name)
    full_path = (agent_root / rel_path).resolve()
    allowed_root = agent_root.resolve()
    # Use Path.relative_to() for robust containment check — raises ValueError
    # if full_path escapes allowed_root (covers symlink-based traversal too).
    try:
        full_path.relative_to(allowed_root)
    except ValueError:
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
    memory = _read_json(_agent_file(name, "_runtime/state/pral_phase.json", "logs/memory.json"))
    if not memory:
        return []
    goals_data = memory.get("goals", {})
    if isinstance(goals_data, dict):
        goals = goals_data.get("value", {})
        if isinstance(goals, dict):
            return list(goals.values())
    return []


def get_agent_memory_notes(name: str, category: str = "") -> list[dict]:
    """Read agent memory notes from agent_notes.jsonl, optionally filtered by category.

    Returns entries in reverse chronological order (most recent first).
    """
    path = _agent_file(name, "cognitive/memory/agent_notes.jsonl", "memory/agent_notes.jsonl")
    if not path.exists():
        return []
    entries = []
    try:
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if category and entry.get("category") != category:
                continue
            # Truncate content for display (keep first 2000 chars)
            content = entry.get("content", "")
            if len(content) > 2000:
                entry["content"] = content[:2000] + "..."
            entries.append(entry)
    except IOError:
        return []
    entries.reverse()  # most recent first
    return entries


def get_agent_memory_stats(name: str) -> dict:
    """Return memory statistics: agent_notes count, episodic memory count, and categories."""
    notes_count = 0
    notes_path = _agent_file(name, "cognitive/memory/agent_notes.jsonl", "memory/agent_notes.jsonl")
    categories: set[str] = set()
    if notes_path.exists():
        try:
            for line in notes_path.read_text(encoding="utf-8").strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                notes_count += 1
                try:
                    entry = json.loads(line)
                    cat = entry.get("category")
                    if cat:
                        categories.add(cat)
                except json.JSONDecodeError:
                    continue
        except IOError:
            pass

    episodic_count = 0
    episodic_path = _agent_file(name, "cognitive/memory/episodic.db", "memory/episodic.db")
    if episodic_path.exists():
        try:
            import sqlite3
            db = sqlite3.connect(f"file:{episodic_path}?mode=ro", uri=True)
            row = db.execute("SELECT COUNT(*) FROM episodic_memory").fetchone()
            if row:
                episodic_count = row[0]
            db.close()
        except Exception:
            pass  # Best-effort: DB might be locked, corrupted, or sqlite3 unavailable

    return {
        "notes_count": notes_count,
        "episodic_count": episodic_count,
        "categories": sorted(categories),
    }


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
