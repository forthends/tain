"""Agent process lifecycle manager — unified subprocess interface."""
import asyncio
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
    """Manages agent process start/stop/restart via supervise_agent.py.

    Provides both sync (blocking) and async (non-blocking) methods.
    Async routes should use the async variants to avoid blocking the event loop.
    """

    def __init__(self, project_root: str | None = None):
        if project_root is None:
            project_root = str(Path(__file__).resolve().parent.parent)
        self._supervisor = str(Path(project_root) / "supervise_agent.py")

    # ── Sync (blocking) methods ──────────────────────────────────────

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

    # ── Async (non-blocking) methods ─────────────────────────────────

    async def _run_async(self, args: list[str], timeout: float = 30.0) -> ProcessResult:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, self._supervisor, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ProcessResult(
                success=False,
                stdout="",
                stderr=f"Process timed out after {timeout}s",
                returncode=-1,
            )
        return ProcessResult(
            success=proc.returncode == 0,
            stdout=stdout.decode("utf-8", errors="replace").strip(),
            stderr=stderr.decode("utf-8", errors="replace").strip(),
            returncode=proc.returncode or 0,
        )

    async def start_async(self, agent_name: str) -> ProcessResult:
        return await self._run_async(["--agent-name", agent_name, "--daemon", "--"])

    async def stop_async(self, agent_name: str) -> ProcessResult:
        return await self._run_async(["--agent-name", agent_name, "--stop"])

    async def restart_async(self, agent_name: str, wait: float = 1.0) -> tuple[ProcessResult, ProcessResult]:
        stop_result = await self.stop_async(agent_name)
        await asyncio.sleep(wait)
        start_result = await self.start_async(agent_name)
        return stop_result, start_result

    async def status_async(self, agent_name: str) -> ProcessResult:
        return await self._run_async(["--agent-name", agent_name, "--status"])
