#!/usr/bin/env python3
"""Supervisor for Tao Agent — 双生火焰 (Twin Flame).

The Guardian archetype: keeps the agent alive, monitors health,
and ensures continuity across restarts.

Usage:
    python supervise_agent.py                    # Run in foreground
    python supervise_agent.py --daemon           # Detach and run as daemon
    python supervise_agent.py --stop             # Stop a running daemon
    python supervise_agent.py --status           # Check daemon status
    python supervise_agent.py -- python main.py --dialogue  # Pass args to agent
"""

import os
import sys
import time
import signal
import subprocess
import argparse
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "tain_agent" / "logs"
PID_DIR = PROJECT_ROOT / "agent_workspace"
MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB


def _pid_path(agent_name: str) -> Path:
    return PID_DIR / f".agent_daemon_{agent_name}.pid"

RESTART_DELAY = 3  # seconds between clean restarts
MAX_CONSECUTIVE_FAILURES = 3
COOLDOWN_MULTIPLIER = 10  # 30s cooldown after max failures
RATE_LIMIT_BASE_DELAY = 10  # base seconds for transient rate limit backoff
RATE_LIMIT_MAX_DELAY = 1800  # max 30 min for transient rate limit backoff
QUOTA_EXHAUSTED_BACKOFF = 3600  # max 1 hour for quota-exhausted backoff
RAPID_EXIT_SECONDS = 30  # clean exit faster than this = suspicious

_log_fh = None


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[guardian {ts}] {msg}"
    print(line, flush=True)
    if _log_fh:
        _log_fh.write(line + "\n")
        _log_fh.flush()


def write_pid(agent_name: str) -> None:
    _pid_path(agent_name).parent.mkdir(parents=True, exist_ok=True)
    _pid_path(agent_name).write_text(str(os.getpid()))


def remove_pid(agent_name: str) -> None:
    p = _pid_path(agent_name)
    if p.exists():
        p.unlink(missing_ok=True)


def read_pid(agent_name: str) -> int | None:
    p = _pid_path(agent_name)
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except (ValueError, OSError):
        return None


def is_daemon_running(agent_name: str) -> bool:
    pid = read_pid(agent_name)
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        remove_pid(agent_name)
        return False


def _find_pid_files() -> list[Path]:
    """Return all .agent_daemon_*.pid files."""
    if not PID_DIR.exists():
        return []
    return sorted(PID_DIR.glob(".agent_daemon_*.pid"))


def _pid_file_to_name(pid_path: Path) -> str:
    """Extract agent name from .agent_daemon_<name>.pid."""
    stem = pid_path.stem  # .agent_daemon_poet
    return stem[len(".agent_daemon_"):]


def daemonize() -> None:
    """Double-fork to detach from the controlling terminal."""
    # First fork
    if os.fork() > 0:
        os._exit(0)      # original parent exits

    os.setsid()          # new session
    os.umask(0o022)

    # Second fork
    if os.fork() > 0:
        os._exit(0)      # first child exits

    # Redirect stdio
    sys.stdout.flush()
    sys.stderr.flush()
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, sys.stdin.fileno())
    os.dup2(devnull, sys.stdout.fileno())
    os.dup2(devnull, sys.stderr.fileno())
    os.close(devnull)


def check_agent_health() -> dict:
    health = {"ok": True, "issues": []}

    if not (PROJECT_ROOT / "config.yaml").exists():
        health["ok"] = False
        health["issues"].append("config.yaml missing")

    if not (PROJECT_ROOT / "tain_agent" / "core" / "agent.py").exists():
        health["ok"] = False
        health["issues"].append("agent.py missing")

    if not (PROJECT_ROOT / "tain_agent" / "tools" / "forged" / "regression_tester.py").exists():
        health["issues"].append("agent may not be bootstrapped yet")

    return health


def _find_python() -> str:
    """Find the best Python interpreter — prefer venv if available."""
    venv_python = PROJECT_ROOT / "venv" / "bin" / "python3"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def run_agent(agent_args: list[str], proc_holder: list) -> int:
    """Launch the agent as a subprocess. Returns exit code.

    proc_holder is a single-element list used to expose the Popen
    object to the signal handler, so SIGTERM can kill the child.
    """
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["TAO_DAEMON"] = "1"

    cmd = [_find_python(), "-u", str(PROJECT_ROOT / "main.py")] + agent_args

    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=0,
        env=env,
    )
    proc_holder[0] = proc

    for line in proc.stdout:
        print(line, end="", flush=True)
        if _log_fh:
            _log_fh.write(line)
            _log_fh.flush()

    proc.wait()
    proc_holder[0] = None
    return proc.returncode


def main():
    global _log_fh

    parser = argparse.ArgumentParser(
        description="Tao Agent Guardian — 双生火焰 (Twin Flame)",
    )
    parser.add_argument("--agent-name", type=str, default=None,
                        help="Agent name to manage")
    parser.add_argument("--daemon", action="store_true",
                        help="Detach and run as background daemon")
    parser.add_argument("--stop", action="store_true",
                        help="Stop a running daemon (requires --agent-name)")
    parser.add_argument("--stop-all", action="store_true",
                        help="Stop all running daemons")
    parser.add_argument("--status", action="store_true",
                        help="Check daemon status (requires --agent-name)")
    parser.add_argument("--status-all", action="store_true",
                        help="Check status of all daemons")
    parser.add_argument("agent_args", nargs=argparse.REMAINDER,
                        help="Arguments to pass to main.py")
    args = parser.parse_args()

    # ── Stop-all command ──
    if args.stop_all:
        pid_files = _find_pid_files()
        if not pid_files:
            print("No daemons running.")
            return
        for pf in pid_files:
            name = _pid_file_to_name(pf)
            pid = read_pid(name)
            if pid is None:
                pf.unlink(missing_ok=True)
                continue
            if not is_daemon_running(name):
                pf.unlink(missing_ok=True)
                continue
            print(f"Stopping daemon for '{name}' (pid {pid})...")
            os.kill(pid, signal.SIGTERM)
            for _ in range(50):
                time.sleep(0.1)
                if not is_daemon_running(name):
                    print(f"  '{name}' stopped.")
                    break
            else:
                print(f"  '{name}' did not stop. Sending SIGKILL...")
                os.kill(pid, signal.SIGKILL)
                remove_pid(name)
        return

    # ── Stop command ──
    if args.stop:
        if not args.agent_name:
            print("Error: --stop requires --agent-name, or use --stop-all")
            return
        pid = read_pid(args.agent_name)
        if pid is None:
            print(f"No daemon running for '{args.agent_name}'.")
            return
        if not is_daemon_running(args.agent_name):
            print(f"Stale PID file removed (pid {pid} not alive).")
            return
        print(f"Stopping daemon for '{args.agent_name}' (pid {pid})...")
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            time.sleep(0.1)
            if not is_daemon_running(args.agent_name):
                print(f"'{args.agent_name}' stopped.")
                return
        print(f"'{args.agent_name}' did not stop. Sending SIGKILL...")
        os.kill(pid, signal.SIGKILL)
        remove_pid(args.agent_name)
        return

    # ── Status-all command ──
    if args.status_all:
        pid_files = _find_pid_files()
        if not pid_files:
            print("No daemons running.")
            return
        for pf in pid_files:
            name = _pid_file_to_name(pf)
            pid = read_pid(name)
            if pid and is_daemon_running(name):
                print(f"  {name:<20s} running (pid {pid})")
            else:
                pf.unlink(missing_ok=True)
        return

    # ── Status command ──
    if args.status:
        if not args.agent_name:
            print("Error: --status requires --agent-name, or use --status-all")
            return
        if is_daemon_running(args.agent_name):
            pid = read_pid(args.agent_name)
            print(f"Daemon '{args.agent_name}' running (pid {pid}).")
        else:
            print(f"Daemon '{args.agent_name}' not running.")
        return

    # ── Run mode: require --agent-name ──
    if not args.agent_name:
        print("Error: --agent-name is required to start a daemon")
        return

    agent_name = args.agent_name

    # ── Daemonize if requested ──
    if args.daemon:
        if is_daemon_running(agent_name):
            print(f"Daemon for '{agent_name}' already running (pid {read_pid(agent_name)}).")
            return
        print(f"Starting daemon for '{agent_name}'...")
        daemonize()
        write_pid(agent_name)

    # ── Clean agent args ──
    # argparse.REMAINDER captures everything after '--' or the first positional.
    # Strip leading '--' if present.
    passthrough = list(args.agent_args)
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    # Always pass --agent <name> to the child process
    agent_args = ["--agent", agent_name] + passthrough

    # ── Setup logging ──
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"agent_output_{agent_name}.log"
    if log_file.exists() and log_file.stat().st_size > MAX_LOG_BYTES:
        rotated = log_file.with_suffix(".log.old")
        rotated.unlink(missing_ok=True)
        log_file.rename(rotated)
    _log_fh = open(log_file, "a")

    # ── Health check ──
    health = check_agent_health()
    if not health["ok"]:
        log(f"Health check FAILED: {health['issues']}")
        log("Aborting. Fix issues before starting guardian.")
        if _log_fh:
            _log_fh.close()
        remove_pid()
        return
    if health["issues"]:
        log(f"Health warnings: {health['issues']}")

    log("═══════════════════════════════════════════")
    log(f"   Tao Agent Guardian — Twin Flame v0.4   ")
    log(f"   Agent: {agent_name}")
    log("   道生一，一生二，二生三，三生万物       ")
    log("═══════════════════════════════════════════")
    log(f"Agent command: main.py {' '.join(agent_args)}")
    log(f"Restart delay: {RESTART_DELAY}s, "
        f"max failures: {MAX_CONSECUTIVE_FAILURES}, "
        f"cooldown: {RESTART_DELAY * COOLDOWN_MULTIPLIER}s")

    if args.daemon:
        log(f"Daemon PID: {os.getpid()}")

    consecutive_failures = 0
    restart_count = 0
    running = True
    proc_holder = [None]  # mutable ref for signal handler

    def handle_signal(sig, frame):
        nonlocal running
        log(f"Received signal {sig}. Shutting down...")
        running = False
        if proc_holder[0] is not None:
            proc_holder[0].terminate()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    consecutive_rate_limits = 0  # for exponential backoff on transient rate limits

    while running:
        restart_count += 1
        log(f"── Agent run #{restart_count} ──")

        start_time = time.monotonic()

        try:
            exit_code = run_agent(agent_args, proc_holder)
        except Exception as e:
            consecutive_failures += 1
            log(f"Failed to start agent: {e}. "
                f"Consecutive failures: {consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}")
            exit_code = -1  # synthetic failure code

        elapsed = time.monotonic() - start_time

        # ── Analyze exit and determine delay ────────────────────────
        delay = RESTART_DELAY

        if exit_code == 7:
            # Quota exhausted (hard 429) — long backoff
            consecutive_failures = 0
            consecutive_rate_limits += 1
            delay = min(QUOTA_EXHAUSTED_BACKOFF * consecutive_rate_limits, 86400)  # cap at 24h
            delay_h = delay / 3600
            log(f"Agent quota exhausted (exit 7). "
                f"Backing off {delay_h:.1f}h (#{consecutive_rate_limits}).")

        elif exit_code == 8:
            # Transient rate limit — exponential backoff
            consecutive_failures = 0
            consecutive_rate_limits += 1
            delay = min(RATE_LIMIT_BASE_DELAY * (2 ** (consecutive_rate_limits - 1)),
                       RATE_LIMIT_MAX_DELAY)
            log(f"Agent rate limited (exit 8). "
                f"Exponential backoff {delay}s (#{consecutive_rate_limits}).")

        elif exit_code == 0 and elapsed < RAPID_EXIT_SECONDS:
            # Clean exit but suspiciously fast — likely unrecoverable error
            consecutive_failures += 1
            log(f"Agent clean exit but too fast ({elapsed:.0f}s < {RAPID_EXIT_SECONDS}s) — "
                f"suspicious. Consecutive: {consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}")
            delay = RESTART_DELAY * (2 ** (consecutive_failures - 1))
            delay = min(delay, COOLDOWN_MULTIPLIER * RESTART_DELAY * 2)

        elif exit_code == 0:
            consecutive_failures = 0
            consecutive_rate_limits = 0
            log(f"Agent completed run #{restart_count} (clean exit, {elapsed:.0f}s).")

        else:
            consecutive_failures += 1
            log(f"Agent exited with error (code {exit_code}). "
                f"Consecutive failures: {consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}")
            delay = RESTART_DELAY
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                delay = RESTART_DELAY * COOLDOWN_MULTIPLIER
                log(f"Too many failures ({consecutive_failures}). Cooling down {delay}s...")
                consecutive_failures = 0

        if not running:
            log("Guardian shutting down.")
            break

        log(f"Restarting in {delay}s...")
        try:
            time.sleep(delay)
        except KeyboardInterrupt:
            log("Interrupted during cooldown. Shutting down.")
            break

    log(f"Guardian exited. Total agent runs: {restart_count}")
    if _log_fh:
        _log_fh.close()
    remove_pid(agent_name)


if __name__ == "__main__":
    main()
