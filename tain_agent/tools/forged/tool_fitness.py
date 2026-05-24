"""
Tool Fitness — check which forged tools are alive vs. dead.

Used by the improvement loop's _eval_tool_fitness evaluator.
"""

import importlib
from pathlib import Path
from tain_agent.core.time_utils import now


def analyze_fitness(forged_dir: str = None,
                    stale_days: int = 30) -> dict:
    root = Path(__file__).resolve().parent.parent.parent.parent
    candidates = [
        root / "agent_workspace" / "forged_tools",
        root / "tain_agent" / "tools" / "forged",
    ]
    if forged_dir:
        candidates.insert(0, Path(forged_dir))

    tools_dir = None
    for d in candidates:
        if d.exists() and any(f.suffix == ".py" and not f.name.startswith("_")
                              for f in d.iterdir()):
            tools_dir = d
            break

    if tools_dir is None:
        return {"dead_tool_ratio": 0.0, "total": 0, "alive": 0, "dead": 0, "stale": 0,
                "details": [], "summary": "No forged tools directory found."}

    py_files = [f for f in sorted(tools_dir.glob("*.py"))
                if not f.name.startswith("_") and f.name != "smart_improve.py"]

    if not py_files:
        return {"dead_tool_ratio": 0.0, "total": 0, "alive": 0, "dead": 0, "stale": 0,
                "details": [], "summary": "No forged tools found."}

    alive, dead, stale = 0, 0, 0
    details = []

    # Ensure project root and workspace on sys.path for importing
    import sys
    project_root = str(Path(__file__).resolve().parent.parent.parent.parent)
    ws_tools = str(Path("agent_workspace/forged_tools").resolve())
    for p in [project_root, ws_tools]:
        if p not in sys.path:
            sys.path.insert(0, p)

    for py_file in py_files:
        name = py_file.stem
        try:
            # Try project-level import first, then bare import from workspace
            try:
                importlib.import_module(f"tain_agent.tools.forged.{name}")
            except ImportError:
                importlib.import_module(name)
            import_ok = True
        except Exception:
            import_ok = False

        # Check file age
        try:
            age_days = (now() - now().__class__.fromtimestamp(py_file.stat().st_mtime)).total_seconds() / 86400 \
                if hasattr(now(), '__class__') else 0
        except Exception:
            age_days = 0

        # Re-check age properly
        import os
        try:
            mtime = py_file.stat().st_mtime
            from datetime import datetime
            age_days = (datetime.now().timestamp() - mtime) / 86400
        except Exception:
            age_days = 0

        status = "alive"
        if not import_ok:
            status = "dead"
            dead += 1
        elif age_days > stale_days:
            status = "stale"
            stale += 1
        else:
            alive += 1

        details.append({
            "tool": name,
            "status": status,
            "import_ok": import_ok,
            "age_days": round(age_days, 1),
        })

    total = len(py_files)
    dead_tool_ratio = round((dead + stale) / total, 3) if total > 0 else 0.0

    return {
        "dead_tool_ratio": dead_tool_ratio,
        "total": total,
        "alive": alive,
        "dead": dead,
        "stale": stale,
        "details": details,
        "summary": f"Tools: {alive} alive, {dead} dead, {stale} stale (dead_ratio={dead_tool_ratio})",
    }


def main(action: str = "analyze_fitness", **kwargs) -> dict:
    return analyze_fitness(**kwargs)
