"""
Dependency Manager — 依赖管理器

Manages third-party package dependencies for forged tools.
Installs allowed packages into an isolated per-agent virtual environment.
Rejected packages generate asynchronous application reports for human review.
"""

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from tain_agent.core.time_utils import now


@dataclass
class ResolveResult:
    """Result of a dependency resolution call."""
    installed: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    applications: list[dict] = field(default_factory=list)


class DependencyManager:
    """Manages package dependencies for forged tools.

    Each agent gets its own isolated virtual environment under its workspace.
    Packages in the allowlist are installed automatically. Packages outside
    the allowlist generate an application report for human review.
    """

    def __init__(self, workspace_dir: str, allowed_packages: list[str],
                 decision_log=None):
        self._workspace_dir = Path(workspace_dir).resolve()
        self._allowed = set(allowed_packages)
        self._decision_log = decision_log
        self._venv_dir = self._workspace_dir / ".forge_venv"
        self._installed: dict[str, set[str]] = {}  # package -> {tool_names}
        self._applications_file = self._workspace_dir / "_forge_applications.jsonl"
        self._ensure_venv()

    def resolve(self, tool_name: str, packages: list[str],
                reason: str = "", alternative_considered: str = "") -> ResolveResult:
        """Resolve a list of dependency specifications.

        Packages in the allowlist are pip-installed into the isolated venv.
        Packages not in the allowlist generate an application report.

        Args:
            tool_name: Name of the tool requesting these dependencies.
            packages: List of pip-compatible package specs (e.g. ["requests>=2.28"]).
            reason: Why this package is needed (used in application reports).
            alternative_considered: Alternative packages considered and why rejected.

        Returns:
            ResolveResult with installed and rejected package names.
        """
        result = ResolveResult()

        for spec in packages:
            pkg_name = spec.split("==")[0].split(">=")[0].split("<=")[0].split("~=")[0].split("!=")[0].split("<")[0].split(">")[0].split("[")[0].strip()
            if pkg_name in self._allowed:
                if pkg_name in self._installed:
                    # Already installed — skip re-installation, just track usage
                    result.installed.append(pkg_name)
                    self._track_install(pkg_name, tool_name)
                elif self._pip_install(spec):
                    result.installed.append(pkg_name)
                    self._track_install(pkg_name, tool_name)
            else:
                result.rejected.append(pkg_name)
                app = self._write_application(
                    tool_name=tool_name,
                    package=spec,
                    reason=reason,
                    alternative_considered=alternative_considered,
                )
                result.applications.append(app)

        self._log_resolve(tool_name, result)
        return result

    def uninstall_orphans(self, tool_name: str) -> list[str]:
        """Find packages that are no longer used by any tool after removal.

        Args:
            tool_name: Name of the tool being removed.

        Returns:
            List of package names that can be safely uninstalled.
        """
        orphans = []
        for pkg, tools in list(self._installed.items()):
            tools.discard(tool_name)
            if not tools:
                orphans.append(pkg)
                del self._installed[pkg]
        return orphans

    def _ensure_venv(self) -> None:
        """Create the isolated venv if it doesn't exist."""
        if self._venv_dir.exists():
            return
        subprocess.run(
            [sys.executable, "-m", "venv", str(self._venv_dir)],
            capture_output=True, text=True, timeout=60,
        )

    def _venv_pip(self) -> str:
        """Return path to the venv's pip executable."""
        if sys.platform == "win32":
            return str(self._venv_dir / "Scripts" / "pip")
        return str(self._venv_dir / "bin" / "pip")

    def _pip_install(self, spec: str) -> bool:
        """pip install a package spec into the isolated venv.

        Returns True if installation succeeded (or package already present).
        """
        pip = self._venv_pip()
        try:
            result = subprocess.run(
                [pip, "install", spec],
                capture_output=True, text=True, timeout=120,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _track_install(self, pkg_name: str, tool_name: str) -> None:
        """Record which tool uses which package."""
        if pkg_name not in self._installed:
            self._installed[pkg_name] = set()
        self._installed[pkg_name].add(tool_name)

    def _write_application(self, tool_name: str, package: str,
                           reason: str = "",
                           alternative_considered: str = "") -> dict:
        """Write a dependency application to the JSONL report file."""
        app = {
            "tool_name": tool_name,
            "package": package,
            "reason": reason,
            "alternative_considered": alternative_considered,
            "requested_at": now().isoformat(),
            "status": "pending",
        }
        try:
            with open(self._applications_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(app, ensure_ascii=False) + "\n")
        except OSError:
            pass
        return app

    def _log_resolve(self, tool_name: str, result: ResolveResult) -> None:
        """Record dependency resolution in the decision log."""
        if not self._decision_log:
            return
        try:
            self._decision_log.record(
                context={"action": "dependency_resolve", "tool_name": tool_name},
                decision_type="dependency_management",
                options_considered=[{"option": "resolve_deps", "packages": result.installed + result.rejected}],
                chosen_option="resolve_deps",
                reasoning=f"Dependencies for '{tool_name}': installed={result.installed}, rejected={result.rejected}",
                expected_outcome=f"Installed: {len(result.installed)}, Rejected: {len(result.rejected)}",
                phase="evolve",
            )
        except Exception:
            pass
