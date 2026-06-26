"""Structured diagnostic feedback — agent diagnoses write to disk for review."""
import json as _json
from datetime import datetime, timezone
from pathlib import Path


def save_diagnostic(agent_name: str, workspace_root: str,
                    diagnosis: dict) -> str:
    """Save an agent's structured diagnostic report to disk.

    Args:
        agent_name: Name of the diagnosing agent.
        workspace_root: Root workspace directory (e.g. 'agent_workspace').
        diagnosis: Dict with keys: category, severity, pattern, affected_tools,
                   root_cause, suggested_fix.

    Returns:
        Path to the saved diagnostic file.
    """
    diag_dir = Path(workspace_root) / agent_name / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filepath = diag_dir / f"{timestamp}.json"

    report = {
        "agent": agent_name,
        "timestamp": timestamp,
        "diagnosis": diagnosis,
    }
    filepath.write_text(
        _json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(filepath)
