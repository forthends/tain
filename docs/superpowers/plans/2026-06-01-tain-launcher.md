# Tain 本地启动封装 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `tain` (POSIX) and `tain.cmd` (Windows) launcher script that auto-syncs dependencies via `uv` and translates subcommands to existing `main.py` arguments, so users can run `./tain run poet` instead of `source .venv/bin/activate && python main.py --agent poet`.

**Architecture:** Two thin shell scripts are pure forwarders — subcommand → argparse-flag translation lives in shell, `main.py` stays untouched. A `tests/test_tain_script.py` file with a `stub_uv` fixture verifies translation correctness without invoking real uv or the LLM stack. A `.venv/.synced` timestamp marker avoids repeated `uv sync` calls.

**Tech Stack:** POSIX bash, Windows cmd batch, `uv` (already required), Python `pytest` (smoke tests), Make, Markdown.

**Spec:** `docs/superpowers/specs/2026-06-01-tain-launcher-design.md`

---

## File Structure

| Path | Type | Responsibility |
|---|---|---|
| `tain` | Create | POSIX shell launcher (macOS/Linux) — subcommand dispatch, uv detection, sync bootstrap, help text |
| `tain.cmd` | Create | Windows batch launcher — same dispatch logic, cmd syntax |
| `tests/test_tain_script.py` | Create | Smoke tests with `stub_uv` fixture for argument translation |
| `Makefile` | Modify | Append `tain` and `tain-%` rules forwarding to `./tain`; leave `test`/`clean`/`run`/`webui` alone |
| `README.md` | Modify | Add `### 安装 uv` section; rewrite Quick Start; add `tain` column to CLI Reference |

**Files NOT touched:** `main.py` (zero Python changes), `tain_agent/**`, `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `webui/**`.

---

## Task 1: Test Harness + Tain Skeleton

**Files:**
- Create: `tests/test_tain_script.py`
- Create: `tain` (minimal version)

- [x] **Step 1.1: Write the test harness**

Create `tests/test_tain_script.py`:

```python
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
    (["run", "a", "b"],              "run python main.py --agent a --agent b"),
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
```

Note: `reset` is **not** auto-tested because the script does `cd "$SCRIPT_DIR"` to the real repo root, so `tain reset` would `rm -rf` the real `.venv`. `reset` is verified manually in Task 9.3.

- [x] **Step 1.2: Run the test to confirm it fails (no tain script yet)**

Run: `python -m pytest tests/test_tain_script.py -v 2>&1 | head -20`
Expected: collection error or all tests fail because `tain` doesn't exist.

- [x] **Step 1.3: Write the minimal `tain` skeleton**

Create `tain`:

```bash
#!/usr/bin/env bash
# Tain launcher — minimal skeleton (Task 1)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

print_help() {
    cat <<'EOF'
Tain — Tain Agent Framework 启动脚本

用法:
  tain run <name>...        启动 agent（多 agent 用空格分隔）
  tain new                  交互式创建 agent
  tain list                 列出所有 agent
  tain state <name>         打印 agent 状态
  tain log <name>           查看决策日志
  tain export <name>        导出为独立包
  tain dialogue <name>      REPL 对话模式
  tain webui [port]         启动 Web UI（默认 8000，自动开浏览器）
  tain daemon <op> [name]   守护进程：op = start|stop|status
  tain reset                删除 .venv（下次启动自动重新同步）
  tain help                 显示本帮助

也支持旧式调用: tain --agent <name> 等，会直接透传给 python main.py。
EOF
}

cmd="${1:-help}"
[ $# -gt 0 ] && shift

case "$cmd" in
    help|-h|--help) print_help ;;
    *)              print_help ;;
esac
```

- [x] **Step 1.4: Make `tain` executable**

Run: `chmod +x tain`
Expected: `ls -l tain` shows `-rwxr-xr-x`.

- [x] **Step 1.5: Run the help tests to verify skeleton**

Run: `python -m pytest tests/test_tain_script.py::test_tain_help_exits_zero tests/test_tain_script.py::test_tain_no_args_shows_help -v`
Expected: PASS for both (the skeleton returns help for both no-args and `help`).

- [x] **Step 1.6: Commit**

```bash
git add tests/test_tain_script.py tain
git commit -m "feat: add tain launcher skeleton with help text and test harness"
```

---

## Task 2: UV Detection and Error Path

**Files:**
- Modify: `tain`

- [x] **Step 2.1: Replace the case statement with uv check + help behavior**

Replace the entire content of `tain` with:

```bash
#!/usr/bin/env bash
# Tain launcher
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv >/dev/null 2>&1; then
    echo "✗ 未找到 uv。请先安装：" >&2
    echo "  macOS:   brew install uv" >&2
    echo "  Linux:   curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    echo "  Windows: winget install astral-sh.uv" >&2
    exit 127
fi

print_help() {
    cat <<'EOF'
Tain — Tain Agent Framework 启动脚本

用法:
  tain run <name>...        启动 agent（多 agent 用空格分隔）
  tain new                  交互式创建 agent
  tain list                 列出所有 agent
  tain state <name>         打印 agent 状态
  tain log <name>           查看决策日志
  tain export <name>        导出为独立包
  tain dialogue <name>      REPL 对话模式
  tain webui [port]         启动 Web UI（默认 8000，自动开浏览器）
  tain daemon <op> [name]   守护进程：op = start|stop|status
  tain reset                删除 .venv（下次启动自动重新同步）
  tain help                 显示本帮助

也支持旧式调用: tain --agent <name> 等，会直接透传给 python main.py。
EOF
}

cmd="${1:-help}"
[ $# -gt 0 ] && shift

case "$cmd" in
    help|-h|--help) print_help ;;
    *)              print_help ;;
esac
```

- [x] **Step 2.2: Verify uv is still required (sanity)**

Run: `command -v uv`
Expected: prints path to `uv` (you have it installed).

- [x] **Step 2.3: Verify help still works with real uv**

Run: `./tain help`
Expected: prints help text, exits 0.

- [x] **Step 2.4: Verify uv-missing path manually (not in test)**

Run: `PATH=/nonexistent ./tain help`
Expected: prints "✗ 未找到 uv" + install instructions, exits 127.

- [x] **Step 2.5: Run all tests**

Run: `python -m pytest tests/test_tain_script.py -v`
Expected: `test_tain_help_exits_zero` and `test_tain_no_args_shows_help` PASS. `test_tain_unknown_subcommand_exits_nonzero` will FAIL (the unknown-subcommand error path is added in Task 5 — this is expected TDD state).

- [x] **Step 2.6: Commit**

```bash
git add tain
git commit -m "feat: add uv detection to tain launcher"
```

---

## Task 3: Bootstrap Sync Logic

**Files:**
- Modify: `tain`

- [x] **Step 3.1: Add `needs_sync` and sync block before subcommand dispatch**

Replace the `tain` file with this (adds sync block between uv check and case statement):

```bash
#!/usr/bin/env bash
# Tain launcher
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv >/dev/null 2>&1; then
    echo "✗ 未找到 uv。请先安装：" >&2
    echo "  macOS:   brew install uv" >&2
    echo "  Linux:   curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    echo "  Windows: winget install astral-sh.uv" >&2
    exit 127
fi

needs_sync() {
    [ ! -d ".venv" ] && return 0
    [ ! -f ".venv/.synced" ] && return 0
    [ "uv.lock" -nt ".venv/.synced" ] && return 0
    return 1
}

if needs_sync; then
    echo "→ 首次启动或 lockfile 变更，同步依赖（~30s）…"
    uv sync --frozen
    touch ".venv/.synced"
fi

print_help() {
    cat <<'EOF'
Tain — Tain Agent Framework 启动脚本

用法:
  tain run <name>...        启动 agent（多 agent 用空格分隔）
  tain new                  交互式创建 agent
  tain list                 列出所有 agent
  tain state <name>         打印 agent 状态
  tain log <name>           查看决策日志
  tain export <name>        导出为独立包
  tain dialogue <name>      REPL 对话模式
  tain webui [port]         启动 Web UI（默认 8000，自动开浏览器）
  tain daemon <op> [name]   守护进程：op = start|stop|status
  tain reset                删除 .venv（下次启动自动重新同步）
  tain help                 显示本帮助

也支持旧式调用: tain --agent <name> 等，会直接透传给 python main.py。
EOF
}

cmd="${1:-help}"
[ $# -gt 0 ] && shift

case "$cmd" in
    help|-h|--help) print_help ;;
    *)              print_help ;;
esac
```

- [x] **Step 3.2: Verify `needs_sync` logic manually**

First, ensure `.venv` is in place and `.venv/.synced` is current:

Run:
```bash
ls -la .venv/.synced 2>/dev/null && echo "FRESH" || echo "STALE_OR_MISSING"
```
Expected: should show FRESH (your environment has a synced venv).

- [x] **Step 3.3: Force stale state and re-run**

```bash
mv .venv .venv.bak
./tain help
echo "exit=$?"
```
Expected: prints "→ 首次启动或 lockfile 变更，同步依赖", runs `uv sync --frozen`, then prints help.

- [x] **Step 3.4: Restore real .venv**

```bash
[ -d .venv.bak ] && rm -rf .venv && mv .venv.bak .venv
ls -la .venv/.synced
```
Expected: `.venv` is back, with `.synced` marker.

- [x] **Step 3.5: Run the help test to confirm no regression**

Run: `python -m pytest tests/test_tain_script.py::test_tain_help_exits_zero -v`
Expected: PASS (sync is a no-op when `.venv/.synced` is fresh, so the help prints normally).

- [x] **Step 3.6: Commit**

```bash
git add tain
git commit -m "feat: add uv sync bootstrap to tain launcher"
```

---

## Task 4: Subcommand Translation — Read-Only + `new` + `run`

**Files:**
- Modify: `tain`

- [x] **Step 4.1: Add the read-only + new + run cases to the case statement**

Replace the `case "$cmd" in ... esac` block (the final block in `tain`) with:

```bash
cmd="${1:-help}"
[ $# -gt 0 ] && shift

case "$cmd" in
    run)        exec uv run python main.py --agent "$@" ;;
    new)        exec uv run python main.py --create-agent ;;
    list)       exec uv run python main.py --list-agents ;;
    state)      exec uv run python main.py --agent "$1" --state ;;
    log)        exec uv run python main.py --agent "$1" --log ;;
    export)     exec uv run python main.py --agent "$1" --export ;;
    dialogue)   exec uv run python main.py --agent "$1" --dialogue ;;
    help|-h|--help) print_help ;;
    *)          print_help ;;
esac
```

- [x] **Step 4.2: Run the parameterized translation tests for these subcommands**

Run: `python -m pytest tests/test_tain_script.py -v -k "subcommand_translation"`
Expected: 7 of the 13 parametrized cases pass:
- `list`, `state poet`, `log poet`, `export poet`, `dialogue poet`, `new`, `run poet`, `run a b`

- [x] **Step 4.3: Manual sanity check (single agent)**

```bash
# Use real uv, real main.py --list-agents (no LLM calls)
./tain list
```
Expected: prints a table of agents (probably empty if no agents yet), exits 0.

- [x] **Step 4.4: Commit**

```bash
git add tain
git commit -m "feat: add read-only, new, and run subcommand translation"
```

---

## Task 5: `webui`, `daemon`, `reset`, Passthrough, and Unknown Subcommand

**Files:**
- Modify: `tain`

- [x] **Step 5.1: Add the remaining cases to the case statement**

Replace the case block with the complete version:

```bash
cmd="${1:-help}"
[ $# -gt 0 ] && shift

case "$cmd" in
    run)        exec uv run python main.py --agent "$@" ;;
    new)        exec uv run python main.py --create-agent ;;
    list)       exec uv run python main.py --list-agents ;;
    state)      exec uv run python main.py --agent "$1" --state ;;
    log)        exec uv run python main.py --agent "$1" --log ;;
    export)     exec uv run python main.py --agent "$1" --export ;;
    dialogue)   exec uv run python main.py --agent "$1" --dialogue ;;
    webui)
        port="${1:-8000}"
        (sleep 1.5 && open "http://localhost:${port}" 2>/dev/null || \
                       xdg-open "http://localhost:${port}" 2>/dev/null || true) &
        exec uv run python main.py --webui --port "$port" ;;
    daemon)
        op="${1:?usage: tain daemon <start|stop|status> [name]}"
        case "$op" in
            start)   name="${2:?missing agent name}"; exec uv run python main.py --daemon start --agent "$name" ;;
            stop)    exec uv run python main.py --daemon stop ;;
            status)  exec uv run python main.py --daemon status ;;
            *)       echo "✗ 未知 daemon 子命令：$op" >&2; exit 1 ;;
        esac ;;
    reset)      rm -rf .venv && echo "✓ 已重置 .venv" ;;
    help|-h|--help) print_help ;;
    --agent|--create-agent|--list-agents|--webui|--daemon|--state|--log|--export)
        exec uv run python main.py "$cmd" "$@" ;;
    *)
        echo "✗ 未知子命令：$cmd" >&2
        echo "  运行 'tain help' 查看用法" >&2
        exit 1
        ;;
esac
```

- [x] **Step 5.2: Run all translation tests**

Run: `python -m pytest tests/test_tain_script.py -v -k "subcommand_translation or passthrough or unknown"`
Expected: all 13 parametrized cases pass, plus `test_tain_passthrough_for_main_py_flag` and `test_tain_unknown_subcommand_exits_nonzero`.

- [x] **Step 5.3: Run the full test file**

Run: `python -m pytest tests/test_tain_script.py -v`
Expected: all tests pass.

- [x] **Step 5.4: Manual test — passthrough**

```bash
./tain --list-agents
```
Expected: same output as `./tain list` (proves passthrough works).

- [x] **Step 5.5: Manual test — unknown subcommand**

```bash
./tain totally-fake-cmd
echo "exit=$?"
```
Expected: prints "✗ 未知子命令：totally-fake-cmd" + "运行 'tain help' 查看用法", exits 1.

- [x] **Step 5.6: Manual test — daemon help error**

```bash
./tain daemon start
echo "exit=$?"
```
Expected: prints "usage: tain daemon <start|stop|status> [name]" or similar, exits 1 (because of `:?` parameter expansion).

- [x] **Step 5.7: Commit**

```bash
git add tain
git commit -m "feat: add webui, daemon, reset, passthrough, and unknown subcommand handling"
```

---

## Task 6: Windows Batch Port (`tain.cmd`)

**Files:**
- Create: `tain.cmd`

- [x] **Step 6.1: Write `tain.cmd`**

Create `tain.cmd`:

```batch
@echo off
rem Tain launcher (Windows)
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

where uv >nul 2>&1
if errorlevel 1 (
    echo X uv not found. Install from: >&2
    echo   winget install astral-sh.uv >&2
    echo   or: https://astral.sh/uv/ >&2
    exit /b 127
)

if not exist ".venv\.synced" goto needs_sync
if not exist ".venv" goto needs_sync
goto skip_sync

:needs_sync
echo ^>^> First run or lockfile change, syncing deps (~30s)...
call uv sync --frozen
if errorlevel 1 exit /b %errorlevel%
echo. > ".venv\.synced"

:skip_sync
if "%~1"=="" goto help
if "%~1"=="help" goto help
if "%~1"=="-h" goto help
if "%~1"=="--help" goto help

set "CMD=%~1"
shift

if "%CMD%"=="run"      goto run
if "%CMD%"=="new"      goto new
if "%CMD%"=="list"     goto list
if "%CMD%"=="state"    goto state
if "%CMD%"=="log"      goto log
if "%CMD%"=="export"   goto do_export
if "%CMD%"=="dialogue" goto dialogue
if "%CMD%"=="webui"    goto webui
if "%CMD%"=="daemon"   goto daemon
if "%CMD%"=="reset"    goto do_reset
goto passthrough

:run
uv run python main.py --agent %*
goto :eof

:new
uv run python main.py --create-agent
goto :eof

:list
uv run python main.py --list-agents
goto :eof

:state
uv run python main.py --agent %1 --state
goto :eof

:log
uv run python main.py --agent %1 --log
goto :eof

:do_export
uv run python main.py --agent %1 --export
goto :eof

:dialogue
uv run python main.py --agent %1 --dialogue
goto :eof

:webui
if "%~1"=="" (
    set "PORT=8000"
) else (
    set "PORT=%~1"
)
start "" "http://localhost:%PORT%"
uv run python main.py --webui --port %PORT%
goto :eof

:daemon
if "%~1"=="" (
    echo Usage: tain daemon ^<start^|stop^|status^> [name] 1>&2
    exit /b 1
)
set "OP=%~1"
if "%OP%"=="start" (
    if "%~2"=="" (
        echo missing agent name 1>&2
        exit /b 1
    )
    uv run python main.py --daemon start --agent %2
) else if "%OP%"=="stop" (
    uv run python main.py --daemon stop
) else if "%OP%"=="status" (
    uv run python main.py --daemon status
) else (
    echo Unknown daemon subcommand: %OP% 1>&2
    exit /b 1
)
goto :eof

:do_reset
rmdir /s /q .venv
echo V reset .venv
goto :eof

:help
echo Tain - Tain Agent Framework launcher
echo.
echo Usage:
echo   tain run ^<name^>...        Start agent^(s^)
echo   tain new                  Interactive agent creation wizard
echo   tain list                 List all agents
echo   tain state ^<name^>         Print agent state
echo   tain log ^<name^>           View decision log
echo   tain export ^<name^>        Export agent as standalone package
echo   tain dialogue ^<name^>      REPL dialogue mode
echo   tain webui [port]         Start Web UI ^(default 8000^)
echo   tain daemon ^<op^> [name]   Daemon: op = start^|stop^|status
echo   tain reset                Delete .venv ^(re-sync on next run^)
echo   tain help                 Show this help
echo.
echo Legacy: tain --agent ^<name^> ... passes through to python main.py.
goto :eof

:passthrough
uv run python main.py %CMD% %*
goto :eof
```

- [x] **Step 6.2: Document Windows testing limitation**

Add a comment header to the file (after the `@echo off`):

Actually, the file already has comment headers. Add this note to README's later Windows section, not to the script.

For now, the task is complete once `tain.cmd` is created. The POSIX tests in `tests/test_tain_script.py` do not cover `tain.cmd` (cross-platform testing isn't supported by the test fixture which is POSIX-specific). Note in the PR/commit that Windows testing was not done locally.

- [x] **Step 6.3: Commit**

```bash
git add tain.cmd
git commit -m "feat: add tain.cmd (Windows batch port)"
```

---

## Task 7: Makefile Integration

**Files:**
- Modify: `Makefile`

- [x] **Step 7.1: Append the `tain` rules**

Read the current `Makefile` (already known: 27 lines), then add to the end:

```makefile

# ─── Tain launcher forwarding ─────────────────────────────────────────────
# Allows `make tain help`, `make tain run poet`, `make tain-run NAME=poet`, etc.
# Forwards all extra args to the ./tain script.

tain:
	./tain $(filter-out $@,$(MAKECMDGOALS))
	@true

tain-%:
	./tain $(subst tain-,,$@) $(filter-out $@,$(MAKECMDGOALS))
	@true

# Make treats extra args as separate targets; this silences "no rule" errors.
%:
	@true
```

Note: the trailing `%` rule is a Make no-op that swallows any unknown targets so `make tain help` doesn't error on the second positional.

- [x] **Step 7.2: Verify `make tain help`**

Run: `make tain help`
Expected: prints tain help text, exits 0.

- [x] **Step 7.3: Verify `make tain-run` is NOT eaten by some pre-existing target**

Run: `make -n tain-run NAME=poet`
Expected: shows `./tain run NAME=poet` (or similar — the variable substitution might or might not happen, depends on Make's target-vs-variable resolution). If NAME=poet is treated as a target, the no-op `%` rule swallows it.

If you see errors, adjust: change `$(filter-out $@,$(MAKECMDGOALS))` to handle the case where `MAKECMDGOALS` contains target-like things.

- [x] **Step 7.4: Verify existing targets still work**

Run: `make -n test`
Expected: shows `python -m pytest tests/ -v` (existing target).

Run: `make -n webui`
Expected: shows `python main.py --webui --port 8000` (existing target).

- [x] **Step 7.5: Commit**

```bash
git add Makefile
git commit -m "feat: add Makefile tain forwarding rules"
```

---

## Task 8: README.md Updates

**Files:**
- Modify: `README.md`

- [x] **Step 8.1: Add `### 安装 uv` section before Quick Start**

Find the line `## Quick Start` (around line 14). Just before it, insert a new section:

```
## 安装 uv

`tain` 启动脚本依赖 [uv](https://docs.astral.sh/uv/) 管理 Python 依赖与虚拟环境（首次运行时自动同步）。

    # macOS
    brew install uv

    # Linux
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Windows
    winget install astral-sh.uv
```

(Use the backtick code-block syntax in the actual file — above uses indented blocks for clarity within this plan.)

- [x] **Step 8.2: Rewrite the Quick Start section**

Replace the entire `## Quick Start` section (lines 14–37) with:

```
## Quick Start

    # 1. 装 uv（参见上文「安装 uv」）
    brew install uv   # macOS  /  参见上文

    # 2. 启动
    ./tain run poet            # 启动 agent（不存在则创建）
    ./tain webui               # 启动 Web UI，自动开浏览器

    # 其他常用
    ./tain list                # 列出所有 agent
    ./tain new                 # 交互式创建 agent
    ./tain state poet          # 查看 agent 状态
    ./tain log poet            # 查看决策日志
    ./tain help                # 完整帮助

> **首次启动**会触发 `uv sync` 自动安装依赖（~30s），后续启动毫秒级。

如需传统方式：

    python3 -m venv .venv && source .venv/bin/activate
    pip install -e ".[dev]"
    python main.py --agent poet

See [Quick Start Guide](docs/quickstart.md) for detailed instructions.
```

- [x] **Step 8.3: Add `tain` column to CLI Reference table**

Find the CLI Reference table (lines 240–254). Replace it with:

```
## CLI Reference

| `tain` 命令 | `python main.py` 旧用法 | 描述 |
|------------------------------------------|---------------------------------------------|---------------------------------|
| `./tain run <name>` | `python main.py --agent <name>` | 启动 agent（不存在则创建） |
| `./tain list` | `python main.py --list-agents` | 列出所有已注册 agent |
| `./tain new` | `python main.py --create-agent` | 交互式创建向导 |
| `./tain state <name>` | `python main.py --agent <name> --state` | 打印 agent 状态 |
| `./tain log <name>` | `python main.py --agent <name> --log` | 查看 agent 决策日志 |
| `./tain export <name>` | `python main.py --agent <name> --export` | 导出 agent 为独立包 |
| `./tain daemon start <name>` | `python main.py --daemon start --agent <name>` | 启动守护进程 |
| `./tain daemon stop` | `python main.py --daemon stop` | 停止守护进程 |
| `./tain daemon status` | `python main.py --daemon status` | 查看守护进程状态 |
| `./tain webui` | `python main.py --webui --port 8000` | 启动 Web UI（自动开浏览器） |
| `./tain reset` | — | 删除 `.venv`（下次启动自动重同步） |
| `./tain help` | `python main.py --help` | 显示帮助 |
```

- [x] **Step 8.4: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README Quick Start around tain launcher"
```

---

## Task 9: Final Verification and Cleanup

**Files:**
- Read: `tain`, `tain.cmd`, `Makefile`, `README.md`, `tests/test_tain_script.py`

- [x] **Step 9.1: Run the tain smoke test suite**

Run: `python -m pytest tests/test_tain_script.py -v`
Expected: all tests pass (help, no-args, unknown, ~13 parametrized translations, passthrough, reset).

- [x] **Step 9.2: Run the full project test suite (regression check)**

Run: `make test 2>&1 | tail -20`
Expected: all 326 existing tests still pass (main.py was not touched, so this is a regression check).

- [x] **Step 9.3: Manual verification checklist (5 items)**

Walk through each:

1. **First run on clean state**:
   ```bash
   mv .venv .venv.bak
   ./tain list
   ls -la .venv/.synced
   # Cleanup: remove the new .venv that uv sync created, then restore the backup
   rm -rf .venv && mv .venv.bak .venv
   ```
   Expected: `tain list` triggers `uv sync`, then lists agents (empty), and `.venv/.synced` is created.

2. **Subsequent run skips sync**:
   ```bash
   time ./tain list
   ```
   Expected: sub-second startup (no `→ 首次启动...` message).

3. **WebUI starts and shows message**:
   ```bash
   # In one terminal
   ./tain webui 8765
   # Check it prints "Tain Agent Framework Web UI" + URL
   # Then Ctrl-C
   ```
   Expected: server starts, prints the URL line, can be killed cleanly.

4. **Passthrough works**:
   ```bash
   ./tain --list-agents
   ./tain --help 2>&1 | head -3
   ```
   Expected: both behave identically to their non-tain counterparts.

5. **Reset removes venv**:
   ```bash
   ./tain reset
   ls -la .venv 2>&1
   ```
   Expected: `.venv` is gone (or error message saying so), no other side effects.

- [x] **Step 9.4: Final commit if any cleanup needed**

If Steps 9.1–9.3 surfaced bugs or polish, fix them now:

```bash
git add -A
git commit -m "fix: address final review findings for tain launcher"
```

If nothing to fix, skip this step.

- [x] **Step 9.5: Print a summary**

Print (for the user's reference):

```
Tain launcher implementation complete.

New files:
  tain              (POSIX shell launcher)
  tain.cmd          (Windows batch launcher)
  tests/test_tain_script.py  (smoke tests, ~16 cases)

Modified files:
  Makefile          (added tain / tain-% forwarding rules)
  README.md         (rewrote Quick Start, added install-uv section, updated CLI Reference)

Test results: X tests pass in tests/test_tain_script.py
Regression:   326 existing tests still pass

Manual checklist: 5/5 verified.
```

---

## Self-Review Checklist (executed during planning)

- [x] **Spec coverage**: Walked each section of `docs/superpowers/specs/2026-06-01-tain-launcher-design.md`
  - Section 1 (背景与目标) → Task 1 creates the foundation that delivers the goal
  - Section 2 (架构) → Tasks 1–3 implement the layered architecture
  - Section 3 (命令映射) → Tasks 4–5 implement every row of the table
  - Section 4 (关键脚本) → Tasks 1–5 build the tain script exactly as specified; Task 6 ports to Windows
  - Section 5 (测试) → Task 1 sets up test harness; Task 9 runs regression
  - Section 6 (文档) → Task 8 implements all README changes
  - Section 7 (风险与权衡) → Windows 引号风险由 Task 6 用 `%*` 而非逐参缓解
  - Section 8 (实施顺序) → Task ordering matches spec ordering

- [x] **Placeholder scan**: No "TBD" / "TODO" / "fill in details" / "similar to Task N" found. Every code block is complete.

- [x] **Type/name consistency**:
  - `.venv/.synced` timestamp marker is used identically in Task 3 (POSIX `touch`), Task 6 (Windows `echo. > .synced`)
  - All 13 subcommand mappings in Task 5's tests match the spec's command-mapping table
  - `print_help` heredoc text is consistent across all tasks that touch the script
  - `test_tain_reset_prints_message` removed (would `rm -rf` real `.venv`); reset verified manually in Task 9.3
  - Task 6 sync logic simplified: `if not exist .venv\.synced goto needs_sync` (the `xcopy` timestamp-comparison was wrong direction and removed)

- [x] **Ambiguity check**:
  - "first run" → clearly defined as `.venv` missing OR `.venv/.synced` missing OR `uv.lock` newer
  - "default port" → 8000, matches main.py default
  - "auto-open browser" → 1.5s delay, macOS `open` / Linux `xdg-open` / Windows `start ""` — each task names the exact command
  - "passthrough" → list of recognized main.py flags in the case statement
