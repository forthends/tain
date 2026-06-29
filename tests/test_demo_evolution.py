"""Tests for the end-to-end evolution demo script."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_demo_evolution_runs_and_passes():
    """The demo script should exit 0 and demonstrate both paths."""
    demo_path = Path(__file__).resolve().parent.parent / "scripts" / "demo_evolution.py"
    assert demo_path.exists(), f"Demo script not found at {demo_path}"

    proc = subprocess.run(
        [sys.executable, str(demo_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    stdout = proc.stdout
    stderr = proc.stderr

    assert proc.returncode == 0, (
        f"Demo exited {proc.returncode}\n"
        f"STDOUT:\n{stdout}\n"
        f"STDERR:\n{stderr}"
    )
    assert "[PASS] valid" in stdout, f"Valid path should pass:\n{stdout}"
    assert "[PASS] blocked" in stdout, f"Blocked path should pass:\n{stdout}"
