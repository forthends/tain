"""
Evolution Reporter — 进化报告器

Generates version-bump evolution reports in the agent's isolated workspace.
Triggered at the end of each successful pipeline registration or
manual version upgrade.

Workflow:
  1. Bump version in workspace version.json (never touches project config.yaml)
  2. Generate a markdown evolution report in workspace/reports/
  3. Record evolution milestone in workspace
"""

import json
import os
import re
import subprocess
from tain_agent.core.time_utils import now
from pathlib import Path


class EvolutionReporter:
    """Handles version bumping, report generation, and git commit/push.

    Designed to be called at the end of a successful self-improvement
    pipeline run, or manually by the agent via the evolve_report tool.
    """

    def __init__(self, base_dir: str = ".", config_path: str = "config.yaml",
                 decision_log=None, memory=None, workspace_dir: str = None):
        self.base_dir = Path(base_dir).resolve()
        self.config_path = Path(config_path)  # project config (read-only reference)
        self.decision_log = decision_log
        self.memory = memory
        self.branch = "evolve"
        self._report_dir = self.base_dir / "reports"
        self._report_dir.mkdir(parents=True, exist_ok=True)
        self._version_file = self.base_dir / "version.json"

    # ── Version bump ──────────────────────────────────────────────────

    def bump_version(self, bump_type: str = "patch") -> dict:
        """Bump the agent's version in its workspace version.json.

        The project config.yaml is never modified — the agent tracks its
        own version within its isolated workspace.

        Args:
            bump_type: "patch" (0.3.0→0.3.1), "minor" (0.3.0→0.4.0),
                       or "major" (0.3.0→1.0.0).

        Returns:
            dict with old_version, new_version, bump_type, success, error.
        """
        import json as _json

        # Read current version from workspace version.json.
        # Each agent instance starts at 0.0.1 — independent of the project version.
        old_version = "0.0.1"
        if self._version_file.exists():
            try:
                data = _json.loads(self._version_file.read_text(encoding="utf-8"))
                old_version = data.get("version", "0.0.1")
            except (json.JSONDecodeError, Exception):
                pass

        new_version = self._increment_version(old_version, bump_type)
        if new_version is None:
            return {"success": False, "error": f"Invalid version format: {old_version}"}

        # Write to workspace version.json
        try:
            self._version_file.write_text(
                _json.dumps({"version": new_version, "bumped_at": now().isoformat()},
                          ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            return {"success": False, "error": f"Failed to write version.json: {e}"}

        return {
            "success": True,
            "old_version": old_version,
            "new_version": new_version,
            "bump_type": bump_type,
        }

    def _increment_version(self, version: str, bump_type: str) -> str | None:
        """Increment a semver string, handling pre-release suffixes."""
        # Strip pre-release suffix (e.g. 2.0.0-dev → 2.0.0)
        base = version.split("-")[0]
        parts = base.split(".")
        if len(parts) < 3:
            parts = (parts + [0, 0, 0])[:3]
        try:
            major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
        except (ValueError, IndexError):
            return None

        if bump_type == "major":
            return f"{major + 1}.0.0"
        elif bump_type == "minor":
            return f"{major}.{minor + 1}.0"
        else:  # patch
            return f"{major}.{minor}.{patch + 1}"

    # ── Report generation ─────────────────────────────────────────────

    def generate_report(self, version_from: str, version_to: str,
                        changes: list[dict] | None = None,
                        pipeline_result: dict | None = None) -> dict:
        """Generate a markdown evolution report with Phase 2 metrics.

        Returns dict with report_path and report content.
        """
        self._report_dir.mkdir(parents=True, exist_ok=True)

        timestamp = now().isoformat()
        safe_version = version_to.replace("/", "_")
        report_path = self._report_dir / f"v{safe_version}_report.md"

        lines = [
            f"# Evolution Report: v{version_from} → v{version_to}",
            "",
            f"**Timestamp**: {timestamp}",
            f"**Branch**: `{self.branch}`",
            "",
            "---",
            "",
            "## Changes Summary",
            "",
        ]

        if changes:
            for ch in changes:
                if isinstance(ch, dict):
                    ch_type = ch.get("type", "unknown")
                    ch_desc = ch.get("description", "")
                    lines.append(f"- **[{ch_type}]** {ch_desc}")
                    if ch.get("detail"):
                        lines.append(f"  - {ch['detail']}")
                else:
                    lines.append(f"- {ch}")
        else:
            lines.append("- (auto-detected from git diff)")

        if pipeline_result:
            lines.extend([
                "",
                "## Pipeline Result",
                "",
            ])
            spec = pipeline_result.get("spec", {})
            lines.append(f"- **Capability**: {spec.get('capability_id', 'N/A')}")
            lines.append(f"- **Tool**: {spec.get('tool_name', 'N/A')}")
            lines.append(f"- **Status**: {'PASSED' if pipeline_result.get('overall_passed') else 'FAILED'}")
            stages = pipeline_result.get("stages", [])
            if stages:
                lines.append("")
                lines.append("### Stages")
                lines.append("")
                lines.append("| Stage | Status | Notes |")
                lines.append("|-------|--------|-------|")
                for s in stages:
                    status = ":white_check_mark:" if s.get("passed") else ":x:"
                    notes = ""
                    if s.get("skipped"):
                        notes = "skipped"
                    elif s.get("error"):
                        notes = str(s.get("error", ""))[:80]
                    lines.append(f"| {s.get('stage', '?')} | {status} | {notes} |")

        # ── Phase 2: Evolution Metrics Dashboard ──────────────────────
        metrics_section = self._build_metrics_section(version_from, version_to)
        if metrics_section:
            lines.extend(metrics_section)

        # Git changes
        git_files = self._get_staged_files()
        if git_files:
            lines.extend([
                "",
                "## Files Changed",
                "",
                "```",
            ])
            lines.extend(git_files)
            lines.append("```")

        lines.extend([
            "",
            "---",
            "",
            f"*Auto-generated by Tain Agent Evolution Reporter at {timestamp}*",
        ])

        report_content = "\n".join(lines)

        try:
            report_path.write_text(report_content, encoding="utf-8")
        except Exception as e:
            return {"success": False, "error": f"Failed to write report: {e}"}

        return {
            "success": True,
            "report_path": str(report_path),
            "report_content": report_content,
        }

    def _build_metrics_section(self, version_from: str, version_to: str) -> list[str]:
        """Build the Phase 2 quantitative metrics section of the report."""
        try:
            from tain_agent.tools.forged.evolution_metrics import (
                MetricsCollector, MetricsComparison, check_degradation,
                save_snapshot, load_snapshot,
            )

            # Collect current metrics
            collector = MetricsCollector(base_dir=str(self.base_dir),
                                         decision_log=self.decision_log,
                                         memory=self.memory)
            current = collector.collect(version=version_to)
            save_snapshot(current, base_dir=str(self.base_dir))

            # Try to load previous snapshot for comparison
            prev = load_snapshot(version_from, base_dir=str(self.base_dir))

            lines = []
            if prev:
                comp = MetricsComparison(prev, current)
                alerts = check_degradation(current, prev)

                lines.extend([
                    "",
                    "## Evolution Metrics Dashboard",
                    "",
                    comp.format_dashboard(),
                ])

                if alerts:
                    lines.extend([
                        "",
                        "### Degradation Alerts",
                        "",
                    ])
                    for a in alerts:
                        sev = {"warning": "⚠️", "critical": "🚨"}.get(a.get("severity", ""), "⚠️")
                        lines.append(
                            f"- {sev} **{a['label']}**: "
                            f"{a['from']} → {a['to']} "
                            f"({a['change_pct']:+.1f}%) — {a.get('suggestion', '')}"
                        )
            else:
                # No previous snapshot — just show current state
                lines.extend([
                    "",
                    "## Evolution Metrics (Baseline)",
                    "",
                    "```",
                    f"  Knowledge Garden:  {current.knowledge_nodes} nodes, {current.knowledge_edges} edges",
                    f"  Tool Efficacy:     {current.tool_total_count} tools, "
                    f"success rate {current.tool_success_rate:.1%}",
                    f"  Code Health:       {current.code_total_lines} lines, "
                    f"{current.code_py_files} .py files",
                    f"  Personality:       {current.personality_dimensions_developed}/"
                    f"{current.personality_total_dimensions} dimensions developed",
                    f"  Evolution:         {current.evolution_improvements_made} improvements "
                    f"in {current.evolution_total_cycles} cycles",
                    "```",
                    "",
                    f"(Baseline established for v{version_to}. Future reports will show comparisons.)",
                ])

            return lines
        except Exception as e:
            return [
                "",
                "## Evolution Metrics",
                "",
                f"*(metrics collection unavailable: {e})*",
            ]

    def _get_staged_files(self) -> list[str]:
        """Get list of files that will be committed (staged + modified)."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                capture_output=True, text=True, timeout=10,
                cwd=str(self.base_dir),
            )
            staged = result.stdout.strip().split("\n") if result.stdout.strip() else []

            untracked = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                capture_output=True, text=True, timeout=10,
                cwd=str(self.base_dir),
            )
            untracked_files = untracked.stdout.strip().split("\n") if untracked.stdout.strip() else []

            return [f for f in staged + untracked_files if f]
        except Exception:
            return []

    # ── Git operations ─────────────────────────────────────────────────

    def commit_and_push(self, message: str) -> dict:
        """Record the evolution milestone in workspace (no project git operations).

        The agent workspace is gitignored — we don't push to the project repo.
        Instead, we log the evolution event for the agent's own records.
        """
        # Record the evolution milestone in the workspace
        milestone = {
            "message": message,
            "timestamp": now().isoformat(),
            "version": self._current_workspace_version(),
        }
        milestones_file = self.base_dir / "evolution_milestones.jsonl"
        try:
            with open(milestones_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(milestone, ensure_ascii=False) + "\n")
        except Exception:
            pass

        return {
            "success": True,
            "message": "Evolution milestone recorded in workspace.",
            "note": "Workspace is gitignored — no project repo push.",
        }

    def _current_workspace_version(self) -> str:
        """Read current version from workspace version.json."""
        if self._version_file.exists():
            try:
                data = json.loads(self._version_file.read_text(encoding="utf-8"))
                return data.get("version", "unknown")
            except Exception:
                pass
        return "unknown"

    # ── Full workflow ─────────────────────────────────────────────────

    def finalize_evolution(self, changes: list[dict] | None = None,
                           bump_type: str = "patch",
                           pipeline_result: dict | None = None) -> dict:
        """Full evolution finalization workflow.

        1. Bump version in workspace version.json
        2. Generate evolution report in workspace/reports/
        3. Record evolution milestone in workspace

        Returns a dict with results from all steps.
        """
        result = {
            "version_bump": None,
            "report": None,
            "git": None,
            "all_success": False,
        }

        # Step 1: Bump version
        version_result = self.bump_version(bump_type)
        result["version_bump"] = version_result
        if not version_result.get("success"):
            result["error"] = f"Version bump failed: {version_result.get('error')}"
            return result

        version_from = version_result["old_version"]
        version_to = version_result["new_version"]

        # Step 2: Generate report
        report_result = self.generate_report(
            version_from, version_to,
            changes=changes,
            pipeline_result=pipeline_result,
        )
        result["report"] = report_result
        if not report_result.get("success"):
            result["error"] = f"Report generation failed: {report_result.get('error')}"
            return result

        # Step 3: Git commit & push
        commit_message = f"evolve: v{version_from} → v{version_to}\n\n{self._format_changes(changes)}"
        git_result = self.commit_and_push(commit_message)
        result["git"] = git_result

        result["all_success"] = git_result.get("success", False)

        # Log to decision log if available
        if self.decision_log:
            self.decision_log.record(
                context={
                    "version_from": version_from,
                    "version_to": version_to,
                    "bump_type": bump_type,
                    "branch": self.branch,
                },
                decision_type="evolution_report",
                options_considered=[
                    {"option": "patch", "description": "0.0.x bugfix/completion"},
                    {"option": "minor", "description": "0.x.0 new capability"},
                    {"option": "major", "description": "x.0.0 breaking change"},
                ],
                chosen_option=bump_type,
                reasoning=f"Version bumped from {version_from} to {version_to} ({bump_type}). "
                          f"Report: {report_result.get('report_path', 'N/A')}. "
                          f"Git: {git_result.get('message', 'N/A')}",
                expected_outcome=f"Version {version_to} committed and pushed to {self.branch}.",
                phase="evolve",
            )

        return result

    def _format_changes(self, changes: list[dict] | None) -> str:
        """Format changes list into a commit message body."""
        if not changes:
            return ""
        lines = []
        for ch in changes:
            if isinstance(ch, dict):
                lines.append(f"- [{ch.get('type', '?')}] {ch.get('description', '')}")
            else:
                lines.append(f"- {ch}")
        return "\n".join(lines)
