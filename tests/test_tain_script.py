"""Smoke tests for the tain launcher script.

These tests stub `uv` to capture its arguments without actually invoking
uv or the LLM stack. They do NOT test sync bootstrap (manual) or
Windows behavior (test on Windows).
"""
import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TAIN_SCRIPT = REPO_ROOT / "tain"


def _run_tain(args, env_overrides=None):
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(TAIN_SCRIPT)] + list(args),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )


@pytest.fixture
def stub_uv(tmp_path, monkeypatch):
    """Replace uv with a script that records its args to UV_RECORD_FILE."""
    record_file = tmp_path / "uv_args.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_stub = bin_dir / "uv"
    uv_stub.write_text(
        "#!/bin/sh\n"
        f'echo "$@" > "{record_file}"\n'
        "exit 0\n"
    )
    uv_stub.chmod(uv_stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")
    return record_file


def test_tain_help_exits_zero():
    r = _run_tain(["help"])
    assert r.returncode == 0, f"stderr: {r.stderr}"
    for cmd in ["run", "new", "list", "webui", "state", "log", "export", "daemon", "reset"]:
        assert cmd in r.stdout, f"help missing subcommand: {cmd}"


def test_tain_no_args_shows_help():
    r = _run_tain([])
    assert r.returncode == 0
    assert "run" in r.stdout and "webui" in r.stdout


def test_tain_unknown_subcommand_exits_nonzero():
    r = _run_tain(["totally-fake-cmd"])
    assert r.returncode != 0
    assert "tain help" in r.stderr or "help" in r.stderr


@pytest.mark.parametrize("tain_cmd,expected_uv_args", [
    (["list"],                       "run python main.py --list-agents"),
    (["state", "poet"],              "run python main.py --agent poet --state"),
    (["log", "poet"],                "run python main.py --agent poet --log"),
    (["export", "poet"],             "run python main.py --agent poet --export"),
    (["dialogue", "poet"],           "run python main.py --agent poet --dialogue"),
    (["new"],                        "run python main.py --create-agent"),
    (["run", "poet"],                "run python main.py --agent poet"),
    (["run", "a"],                   "run python main.py --agent a"),
    (["webui"],                      "run python main.py --webui --port 8000"),
    (["webui", "8080"],              "run python main.py --webui --port 8080"),
    (["daemon", "start", "poet"],    "run python main.py --daemon start --agent poet"),
    (["daemon", "stop"],             "run python main.py --daemon stop"),
    (["daemon", "status"],           "run python main.py --daemon status"),
])
def test_tain_subcommand_translation(stub_uv, tain_cmd, expected_uv_args):
    r = _run_tain(tain_cmd)
    assert r.returncode == 0, f"tain exited {r.returncode}: {r.stderr}"
    recorded = stub_uv.read_text().strip()
    assert recorded == expected_uv_args, (
        f"expected '{expected_uv_args}', got '{recorded}'"
    )


def test_tain_passthrough_for_main_py_flag(stub_uv):
    """Unrecognized main.py flags (--list-agents, --agent, etc.) pass through."""
    r = _run_tain(["--list-agents"])
    assert r.returncode == 0, f"tain exited {r.returncode}: {r.stderr}"
    recorded = stub_uv.read_text().strip()
    assert recorded == "run python main.py --list-agents"
