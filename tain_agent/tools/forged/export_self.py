"""
export_self — Agent-initiated export tool.

Allows the agent to request its own "birth" as a standalone executable.
Runs the quality gate and export pipeline when the agent determines it
is ready to leave the factory.

Design: Phase 3 §6.2.
"""

import json
from pathlib import Path

SCHEMA = {
    "name": "export_self",
    "description": (
        "Request export as a standalone agent. This runs the full quality gate "
        "evaluation (7 hard gates + 8 scoring gates, must score ≥ 0.80) and "
        "if passed, produces a self-contained executable in dist/. "
        "Use this when you believe you are ready to operate independently."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name for the exported agent (e.g. 'explorer').",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory for the exported package (default: 'dist').",
            },
            "skip_gate": {
                "type": "boolean",
                "description": "Skip quality gate check (development only, not recommended).",
            },
        },
        "required": ["name"],
    },
}


def main(name: str, output_dir: str = "dist", skip_gate: bool = False) -> dict:
    """Run the export pipeline and return the result.

    Args:
        name: Agent name for the exported package.
        output_dir: Directory to write the .tar.gz package.
        skip_gate: If True, bypass the quality gate (dangerous in production).

    Returns:
        dict with export result: name, version, output_path, tool_count,
        knowledge_count, total_size_bytes, verification, quality_gate.
    """
    from tain_agent.evolution.exporter import ExportPipeline
    from tain_agent.evolution.quality_gate import ExportQualityGate, render_report

    ws = Path("agent_workspace")
    workspace = str(ws) if ws.exists() else None

    pipeline = ExportPipeline(workspace_dir=workspace)

    if not skip_gate:
        gate = ExportQualityGate(agent_name=name)
        report = gate.evaluate()

        if not report.passed:
            return {
                "exported": False,
                "reason": "Quality gate not passed",
                "quality_gate": {
                    "hard_passed": report.hard_passed,
                    "hard_pass_count": report.hard_pass_count,
                    "total_score": report.total_score,
                    "grade": report.grade,
                    "failures": report.failures(),
                },
                "report_text": render_report(report),
                "recommendation": (
                    "Address the failures listed above and try again. "
                    "Focus on the hard gate failures first."
                ),
            }

    try:
        result = pipeline.export(name, output_dir=output_dir, skip_gate=skip_gate)
    except Exception as exc:
        return {
            "exported": False,
            "reason": f"Export pipeline failed: {exc}",
            "error": str(exc),
        }

    return {
        "exported": True,
        "name": result.name,
        "version": result.version,
        "output_path": result.output_path,
        "tool_count": result.tool_count,
        "knowledge_count": result.knowledge_count,
        "total_size_bytes": result.total_size_bytes,
        "verification": result.verification,
        "message": (
            f"Successfully exported {result.name} v{result.version} "
            f"with {result.tool_count} tools and {result.knowledge_count} "
            f"knowledge documents. Package: {result.output_path} "
            f"({result.total_size_bytes:,} bytes). "
            f"Verification: {'ALL OK' if result.verification.get('all_ok') else 'ISSUES FOUND'}."
        ),
    }


if __name__ == "__main__":
    import sys
    result = main(
        name=sys.argv[1] if len(sys.argv) > 1 else "agent",
        output_dir=sys.argv[2] if len(sys.argv) > 2 else "dist",
        skip_gate="--skip-gate" in sys.argv,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
