"""
Background Process Manager — async subprocess lifecycle for long-running commands.

Lets an agent start, monitor, and kill background processes (e.g. servers,
test suites, batch operations) that exceed typical tool execution timeouts.

Uses asyncio subprocess for non-blocking I/O. The exposed primal tools are
sync wrappers so they work with the existing ThreadPool-based ToolRegistry.
"""

import asyncio
import os
import signal
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class BackgroundProcess:
    """A tracked background subprocess."""

    id: str
    command: str
    process: asyncio.subprocess.Process
    started_at: str
    output_buffer: list[str] = field(default_factory=list)
    _max_buffer: int = 2000


class BackgroundShellManager:
    """Manages a pool of async background processes for a single agent.

    Thread-safe design: all async subprocess operations are dispatched
    to a dedicated asyncio event loop running in a background thread.
    """

    MAX_PROCESSES = 5

    def __init__(self, workspace_dir: str = ""):
        self.workspace_dir = workspace_dir
        self.processes: dict[str, BackgroundProcess] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """Get or create a dedicated event loop for subprocess management."""
        if self._loop is None or self._loop.is_closed():
            import threading
            self._loop = asyncio.new_event_loop()
            t = threading.Thread(target=self._loop.run_forever, daemon=True)
            t.start()
        return self._loop

    # ── Public API (sync wrappers) ─────────────────────────────────

    def start(self, command: str) -> dict:
        """Start a command in the background. Returns process info."""
        if len(self.processes) >= self.MAX_PROCESSES:
            return {
                "success": False,
                "error": f"Process limit reached ({self.MAX_PROCESSES}). "
                         f"Kill an existing process first with bg_kill.",
            }

        proc_id = f"bg_{uuid.uuid4().hex[:8]}"
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._async_start(proc_id, command), loop
        )
        try:
            return future.result(timeout=10)
        except Exception as e:
            return {"success": False, "error": str(e), "process_id": proc_id}

    def get_output(self, process_id: str, tail_lines: int = 50) -> dict:
        """Read buffered output from a background process."""
        proc = self.processes.get(process_id)
        if proc is None:
            return {
                "success": False,
                "error": f"No process with id '{process_id}'. "
                         f"Active: {list(self.processes.keys())}",
            }

        buf = proc.output_buffer
        if not buf:
            return {
                "success": True,
                "process_id": process_id,
                "output": "",
                "lines": 0,
                "running": proc.process.returncode is None,
            }

        shown = buf[-tail_lines:]
        return {
            "success": True,
            "process_id": process_id,
            "output": "\n".join(shown),
            "lines": len(shown),
            "total_lines": len(buf),
            "running": proc.process.returncode is None,
        }

    def kill(self, process_id: str) -> dict:
        """Kill a background process by ID."""
        proc = self.processes.get(process_id)
        if proc is None:
            return {
                "success": False,
                "error": f"No process with id '{process_id}'.",
            }

        try:
            p = proc.process
            if p.returncode is None:
                p.send_signal(signal.SIGTERM)
                # Give it a moment, then force kill
                try:
                    import time as _time
                    deadline = _time.monotonic() + 3
                    while p.returncode is None and _time.monotonic() < deadline:
                        _time.sleep(0.1)
                    if p.returncode is None:
                        p.send_signal(signal.SIGKILL)
                except Exception:
                    pass
            return {
                "success": True,
                "process_id": process_id,
                "exit_code": p.returncode,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            self.processes.pop(process_id, None)

    def list_processes(self) -> dict:
        """List all running background processes."""
        procs = []
        for pid, proc in self.processes.items():
            rc = proc.process.returncode
            procs.append({
                "id": pid,
                "command": proc.command,
                "started_at": proc.started_at,
                "running": rc is None,
                "exit_code": rc,
                "output_lines": len(proc.output_buffer),
            })
        return {
            "success": True,
            "processes": procs,
            "total": len(procs),
            "limit": self.MAX_PROCESSES,
        }

    def wait(self, process_id: str, timeout: float = 30.0) -> dict:
        """Wait for a background process to complete."""
        proc = self.processes.get(process_id)
        if proc is None:
            return {
                "success": False,
                "error": f"No process with id '{process_id}'.",
            }

        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._async_wait(process_id, timeout), loop
        )
        try:
            return future.result(timeout=timeout + 5)
        except Exception as e:
            return {"success": False, "error": str(e), "process_id": process_id}

    def kill_all(self) -> int:
        """Kill all running processes. Returns count of processes killed."""
        count = 0
        for pid in list(self.processes.keys()):
            result = self.kill(pid)
            if result.get("success"):
                count += 1
        return count

    # ── Async internals ────────────────────────────────────────────

    import shlex

    async def _async_start(self, proc_id: str, command: str) -> dict:
        cwd = self.workspace_dir or None
        proc = await asyncio.create_subprocess_exec(
            *shlex.split(command),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
            preexec_fn=os.setsid if hasattr(os, 'setsid') else None,
        )

        from tain_agent.core.time_utils import now

        bg = BackgroundProcess(
            id=proc_id,
            command=command,
            process=proc,
            started_at=now().isoformat(),
        )
        self.processes[proc_id] = bg

        # Start background reader
        asyncio.ensure_future(self._read_output(proc_id), loop=self._loop)

        return {
            "success": True,
            "process_id": proc_id,
            "command": command,
            "started_at": bg.started_at,
        }

    async def _read_output(self, proc_id: str) -> None:
        """Read stdout lines in background until process exits."""
        proc = self.processes.get(proc_id)
        if proc is None:
            return

        try:
            while True:
                line = await asyncio.wait_for(
                    proc.process.stdout.readline(), timeout=3600
                )
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\n")
                proc.output_buffer.append(text)
                if len(proc.output_buffer) > proc._max_buffer:
                    proc.output_buffer = proc.output_buffer[-proc._max_buffer:]
        except (asyncio.TimeoutError, Exception):
            pass
        finally:
            # Ensure process is awaited
            try:
                await proc.process.wait()
            except Exception:
                pass

    async def _async_wait(self, proc_id: str, timeout: float) -> dict:
        proc = self.processes.get(proc_id)
        if proc is None:
            return {"success": False, "error": f"Process {proc_id} not found."}

        p = proc.process
        if p.returncode is not None:
            return {
                "success": True,
                "process_id": proc_id,
                "exit_code": p.returncode,
                "output": "\n".join(proc.output_buffer[-100:]),
                "already_finished": True,
            }

        try:
            exit_code = await asyncio.wait_for(p.wait(), timeout=timeout)
            return {
                "success": True,
                "process_id": proc_id,
                "exit_code": exit_code,
                "output": "\n".join(proc.output_buffer[-100:]),
            }
        except asyncio.TimeoutError:
            return {
                "success": True,
                "process_id": proc_id,
                "exit_code": None,
                "output": "\n".join(proc.output_buffer[-100:]),
                "timed_out": True,
                "message": f"Process still running after {timeout}s.",
            }


# ── Module-level singleton ──────────────────────────────────────────────

_manager: Optional[BackgroundShellManager] = None


def get_manager() -> BackgroundShellManager:
    global _manager
    if _manager is None:
        _manager = BackgroundShellManager()
    return _manager


def init_manager(workspace_dir: str) -> BackgroundShellManager:
    global _manager
    _manager = BackgroundShellManager(workspace_dir=workspace_dir)
    return _manager


# ── Primal tool functions ────────────────────────────────────────────────


def bg_start(command: str) -> dict:
    """Start a long-running command in the background."""
    return get_manager().start(command)


def bg_output(process_id: str, tail_lines: int = 50) -> dict:
    """Read buffered output from a background process."""
    return get_manager().get_output(process_id, tail_lines=tail_lines)


def bg_kill(process_id: str) -> dict:
    """Kill a background process by ID."""
    return get_manager().kill(process_id)


def bg_list() -> dict:
    """List all running background processes."""
    return get_manager().list_processes()


def bg_wait(process_id: str, timeout: float = 30.0) -> dict:
    """Wait for a background process to complete."""
    return get_manager().wait(process_id, timeout=timeout)


def register_bg_tools(registry, workspace_dir: str = "") -> None:
    """Register background process management tools on the registry."""
    init_manager(workspace_dir)

    registry.register(
        "bg_start", bg_start,
        "Start a long-running command in the background. Use for servers, "
        "test suites, batch operations. Returns a process_id for monitoring. "
        f"Max {BackgroundShellManager.MAX_PROCESSES} concurrent processes.",
        {
            "command": {"type": "string", "description": "Shell command to run in background.", "required": True},
        },
    )
    registry.register(
        "bg_output", bg_output,
        "Read buffered output from a background process. Only returns "
        "new output since the process started.",
        {
            "process_id": {"type": "string", "description": "Process ID from bg_start.", "required": True},
            "tail_lines": {"type": "integer", "description": "Number of recent lines to return (default 50).", "required": False},
        },
    )
    registry.register(
        "bg_kill", bg_kill,
        "Kill a running background process by ID. Sends SIGTERM first, "
        "then SIGKILL after 3 seconds if still alive.",
        {
            "process_id": {"type": "string", "description": "Process ID from bg_start.", "required": True},
        },
    )
    registry.register(
        "bg_list", bg_list,
        "List all running background processes with their IDs, commands, "
        "and status.",
    )
    registry.register(
        "bg_wait", bg_wait,
        "Wait for a background process to complete and return its output "
        "and exit code. Times out after the specified duration.",
        {
            "process_id": {"type": "string", "description": "Process ID from bg_start.", "required": True},
            "timeout": {"type": "number", "description": "Max seconds to wait (default 30).", "required": False},
        },
    )
