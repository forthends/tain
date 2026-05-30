"""Agent process lifecycle manager — unified subprocess interface."""
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProcessResult:
    success: bool
    stdout: str
    stderr: str
    returncode: int


class ProcessManager:
    """Manages agent process start/stop/restart via supervise_agent.py."""

    def __init__(self, project_root: str | None = None):
        if project_root is None:
            project_root = str(Path(__file__).resolve().parent.parent)
        self._supervisor = str(Path(project_root) / "supervise_agent.py")

    def _run(self, args: list[str], timeout: float = 30.0) -> ProcessResult:
        result = subprocess.run(
            [sys.executable, self._supervisor, *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return ProcessResult(
            success=result.returncode == 0,
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
            returncode=result.returncode,
        )

    def start(self, agent_name: str) -> ProcessResult:
        return self._run(["--agent-name", agent_name, "--daemon", "--"])

    def stop(self, agent_name: str) -> ProcessResult:
        return self._run(["--agent-name", agent_name, "--stop"])

    def restart(self, agent_name: str, wait: float = 1.0) -> tuple[ProcessResult, ProcessResult]:
        stop_result = self.stop(agent_name)
        time.sleep(wait)
        start_result = self.start(agent_name)
        return stop_result, start_result

    def status(self, agent_name: str) -> ProcessResult:
        return self._run(["--agent-name", agent_name, "--status"])
