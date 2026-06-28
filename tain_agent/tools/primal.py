"""
Primal Tools — 原始工具

The first tools the Tain Agent is born with.
These are the "senses" it uses to explore the world.

All file operations are scoped to the agent's isolated workspace.
The agent CANNOT read or modify any file outside its workspace.

observe  → perceive the environment (workspace only)
act      → execute an action (workspace-scoped)
reflect  → think deeply about observations
decide   → make a choice and log it
"""

import os
from pathlib import Path
from tain_agent.core.time_utils import now


# ─── Workspace isolation ────────────────────────────────────────────────

# Set by register_primal_tools — the agent's isolated workspace path.
_WORKSPACE_DIR: Path | None = None

# Project files the agent may READ (but never modify) for bootstrap awareness.
# This is a narrow, explicit whitelist. The agent cannot explore or search
# for these — it only gets access when asking for these specific paths.
_READABLE_PROJECT_FILES = frozenset({
    "config.yaml",  # so the agent knows its own configuration
})


def _resolve_path(path: str, for_write: bool = False) -> Path | None:
    """Resolve a path within the agent's workspace. Returns None if denied.

    Rules:
      - Relative paths → resolved within workspace
      - Absolute paths within workspace → allowed
      - Paths already prefixed with workspace dir → strip prefix to avoid nesting
      - Paths in _READABLE_PROJECT_FILES → read-only allowed
      - Everything else → DENIED (returns None)
    """
    if _WORKSPACE_DIR is None:
        return Path(path)  # no isolation configured (legacy mode)

    p = Path(path)
    ws = _WORKSPACE_DIR.resolve()
    ws_name = ws.name  # e.g. "agent_workspace"

    if p.is_absolute():
        # Absolute path — must be within workspace
        try:
            p.resolve()
            if str(p.resolve()).startswith(str(ws)):
                return p
        except Exception:
            pass
        # Check if it matches a readable project file
        if not for_write:
            for allowed in _READABLE_PROJECT_FILES:
                if str(p) == str(Path(allowed).resolve()):
                    return p
                if p.name == allowed or str(p).endswith(allowed):
                    return p
        return None  # DENIED
    else:
        # Relative path — check whitelist first, then resolve within workspace
        if not for_write:
            for allowed in _READABLE_PROJECT_FILES:
                if p == Path(allowed) or str(p) == allowed:
                    return Path(allowed).resolve()

        # Strip workspace dir prefix if the agent already prepended it.
        # This prevents double-nesting: ws / "agent_workspace/foo" → ws/foo
        parts = p.parts
        if parts and parts[0] == ws_name:
            p = Path(*parts[1:]) if len(parts) > 1 else Path(".")

        # Resolve within workspace
        resolved = (ws / p).resolve()
        if str(resolved).startswith(str(ws)):
            return resolved
        return None


# ─── Tool functions ──────────────────────────────────────────────────────

def observe_environment() -> str:
    """Scan and describe the agent's workspace contents."""
    cwd = _WORKSPACE_DIR if _WORKSPACE_DIR else Path.cwd()
    items = []
    try:
        for entry in sorted(cwd.iterdir()):
            if entry.name.startswith("."):
                continue  # skip hidden files
            entry_type = "dir" if entry.is_dir() else "file"
            size = ""
            if entry.is_file():
                try:
                    size = f" ({entry.stat().st_size} bytes)"
                except OSError:
                    pass
            items.append(f"  [{entry_type}] {entry.name}{size}")
    except PermissionError:
        return f"工作区: {cwd}\n(无法列出内容 — 权限不足)"

    header = f"🔒 隔离工作区: {cwd}\n内容:"
    return header + "\n" + ("\n".join(items) if items else "  (空)") if items else header + "\n  (空)"


def explore_directory(path: str = ".") -> str:
    """Recursively list files in a directory within the agent's workspace."""
    target = _resolve_path(path)
    if target is None:
        return f"🔒 访问被拒绝: '{path}' 不在你的隔离工作区内。你只能探索自己的工作区目录。"
    if not target.exists():
        return f"路径不存在: {target}"
    if not target.is_dir():
        return f"不是目录: {target}"

    output = [f"目录树: {target}"]
    for root, dirs, files in os.walk(target):
        level = len(Path(root).relative_to(target).parts)
        indent = "  " * level
        dir_name = Path(root).name or str(root)
        output.append(f"{indent}[{dir_name}/]")
        for f in files:
            if f.startswith("."):
                continue
            output.append(f"{indent}  {f}")
        if level >= 3:  # limit depth
            output.append(f"{indent}  ... (已达最大深度)")
            dirs.clear()
    return "\n".join(output)


def read_file(path: str) -> str:
    """Read a file within the agent's workspace (or a whitelisted project file)."""
    target = _resolve_path(path, for_write=False)
    if target is None:
        return (f"🔒 访问被拒绝: '{path}' 不在你的隔离工作区内。\n"
                f"   你只能读取工作区 ({_WORKSPACE_DIR}) 内的文件。\n"
                f"   项目源代码对你不可见。")
    if not target.exists():
        return (f"文件未找到: '{path}'\n"
                f"   (路径解析为工作区内: {target})\n"
                f"   项目源代码在你的工作区之外，无法被访问。")
    try:
        content = target.read_text(encoding="utf-8")
        from tain_agent.utils.token_utils import truncate_text_by_tokens
        return truncate_text_by_tokens(content, max_tokens=32000)
    except UnicodeDecodeError:
        return f"无法读取 {path}: 不是文本文件 (二进制)"
    except PermissionError:
        return f"无法读取 {path}: 权限不足"


def write_file(path: str, content: str) -> str:
    """Write content to a file within the agent's workspace. ONLY."""
    target = _resolve_path(path, for_write=True)
    if target is None:
        return (f"🔒 写入被拒绝: '{path}' 不在你的隔离工作区内。\n"
                f"   所有文件写入必须在你自己的工作区 ({_WORKSPACE_DIR}) 内进行。\n"
                f"   项目源代码不能被修改。")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_text(content, encoding="utf-8")
        return f"文件已写入: {target} ({len(content)} 字符)"
    except Exception as e:
        return f"写入失败 {path}: {e}"


def _validate_url(url: str) -> str | None:
    """Validate a URL for safe fetching. Returns error message or None if safe."""
    from urllib.parse import urlparse
    import ipaddress
    import socket

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Blocked URL scheme '{parsed.scheme}': only http/https allowed."

    hostname = parsed.hostname
    if not hostname:
        return "Cannot determine hostname from URL."

    hostname_lower = hostname.lower()
    blocked_hosts = ("localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal")
    if hostname_lower in blocked_hosts:
        return f"Blocked internal host: {hostname}"

    if hostname_lower.endswith(".local") or hostname_lower.endswith(".internal"):
        return f"Blocked internal host suffix: {hostname}"

    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            return f"Blocked IP address: {hostname}"
    except ValueError:
        try:
            resolved = socket.getaddrinfo(hostname, None)
            for _, _, _, _, sockaddr in resolved:
                addr = sockaddr[0]
                try:
                    ip = ipaddress.ip_address(addr)
                    if ip.is_loopback or ip.is_private or ip.is_link_local:
                        return f"Blocked resolution to private/internal IP: {hostname} → {addr}"
                except ValueError:
                    pass
        except socket.gaierror:
            return f"Cannot resolve hostname: {hostname}"

    return None


def web_fetch(url: str) -> str:
    """Fetch content from a URL and return as text."""
    try:
        import requests
    except ImportError:
        return "Cannot fetch URL: 'requests' library not installed."
    error = _validate_url(url)
    if error:
        return f"Cannot fetch URL: {error}"
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Tao-Agent/0.1"}, allow_redirects=True)
        # Validate the final URL after redirects
        final_error = _validate_url(resp.url)
        if final_error:
            return f"Cannot fetch URL (redirect target): {final_error}"
        resp.raise_for_status()
        content = resp.text[:8000]
        return f"Fetched {url} (status {resp.status_code}, {len(resp.text)} bytes):\n\n{content}"
    except Exception as e:
        return f"Failed to fetch {url}: {e}"


def web_search(query: str, max_results: int = 5) -> str:
    """Search the web using DuckDuckGo."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return "Cannot search web: 'ddgs' library not installed."
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return f"No results found for: {query}"
        output = [f"Web search results for '{query}':"]
        for i, r in enumerate(results, 1):
            output.append(f"  {i}. {r.get('title', 'N/A')}")
            output.append(f"     {r.get('href', 'N/A')}")
            output.append(f"     {r.get('body', 'N/A')[:200]}")
        return "\n".join(output)
    except Exception as e:
        return f"Search failed: {e}"


def execute_code(code: str, timeout: int = 30) -> str:
    """Execute arbitrary Python code in a workspace-sandboxed environment.

    All file writes are redirected to the agent's workspace. File reads outside
    the workspace raise PermissionError. This prevents agent code from leaking
    files into the project directory.

    Standard library imports are allowed via a whitelist so the agent can
    write and test meaningful code (json, pathlib, datetime, etc.).
    """
    import sys
    import builtins as _builtins
    from io import StringIO
    from pathlib import Path as _PathLibPath

    old_stdout = sys.stdout
    sys.stdout = StringIO()

    ws = _WORKSPACE_DIR.resolve() if _WORKSPACE_DIR else None
    _original_open = _builtins.open
    _original_import = _builtins.__import__

    # Stdlib whitelist for execute_code sandbox.
    # Note: forge_tool sandbox uses tain_agent.tools.sandbox_allowlist.SANDBOX_ALLOWED_MODULES.
    # This whitelist is specific to execute_code and may diverge intentionally.
    _STDLIB_WHITELIST = frozenset({
        "json", "re", "pathlib", "datetime", "collections", "functools",
        "itertools", "math", "statistics", "textwrap", "hashlib",
        "uuid", "random", "typing", "dataclasses", "enum", "string",
        "decimal", "fractions", "numbers", "copy", "pprint", "time",
        "io", "csv", "base64", "binascii", "html", "xml", "urllib.parse",
        "tain_agent.core.time_utils",
    })

    def _sandboxed_import(name, *args, **kwargs):
        if name in _STDLIB_WHITELIST or name.startswith("tain_agent."):
            return _original_import(name, *args, **kwargs)
        hint = ""
        if name == "os":
            hint = " Use 'pathlib.Path' instead of 'os.path' for file operations."
        elif name == "sys":
            hint = " Use 'pathlib' and environment-agnostic patterns instead."
        elif name in ("subprocess", "shutil"):
            hint = " Subprocess and shell operations are not available in the sandbox."
        raise ImportError(
            f"Module '{name}' is not in the execute_code whitelist.{hint}\n"
            f"Allowed: {sorted(_STDLIB_WHITELIST)}"
        )

    if ws:
        # ── Sandboxed open() ──────────────────────────────────────────
        def _sandboxed_open(file, mode='r', *args, **kwargs):
            p = _PathLibPath(file)
            p = p.resolve() if p.is_absolute() else (_PathLibPath.cwd() / p).resolve()

            if any(c in mode for c in ('w', 'a', 'x')):
                # Writes outside workspace → redirect to workspace/files/
                if not str(p).startswith(str(ws)):
                    rel = str(p).lstrip('/')
                    p = ws / 'files' / 'sandbox_redirects' / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                return _original_open(str(p), mode, *args, **kwargs)

            # Reads outside workspace → deny
            if not str(p).startswith(str(ws)):
                raise PermissionError(
                    f"🔒 访问被拒绝: '{file}' 不在你的隔离工作区内。"
                    f"项目源代码不可访问。"
                )
            return _original_open(str(p), mode, *args, **kwargs)

        # ── Sandboxed Path class ──────────────────────────────────────
        # Replaces pathlib.Path in the executed code so that write_text,
        # open, mkdir, touch are all workspace-scoped.
        class SandboxedPath(_PathLibPath):
            def write_text(self, data, encoding=None, errors=None):
                p = self.resolve()
                if not str(p).startswith(str(ws)):
                    rel = str(p).lstrip('/')
                    p = ws / 'files' / 'sandbox_redirects' / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                return _PathLibPath.write_text(p, data, encoding=encoding, errors=errors)

            def open(self, mode='r', buffering=-1, encoding=None, errors=None, newline=None):
                p = self.resolve()
                if not str(p).startswith(str(ws)):
                    if any(c in mode for c in ('w', 'a', 'x')):
                        rel = str(p).lstrip('/')
                        p = ws / 'files' / 'sandbox_redirects' / rel
                        p.parent.mkdir(parents=True, exist_ok=True)
                    else:
                        raise PermissionError(
                            f"🔒 访问被拒绝: '{self}' 不在你的隔离工作区内。"
                        )
                return _PathLibPath.open(p, mode, buffering=buffering,
                                        encoding=encoding, errors=errors, newline=newline)

            def mkdir(self, mode=0o777, parents=False, exist_ok=False):
                p = self.resolve()
                if not str(p).startswith(str(ws)):
                    rel = str(p).lstrip('/')
                    p = ws / 'files' / 'sandbox_redirects' / rel
                return _PathLibPath.mkdir(p, mode=mode, parents=parents, exist_ok=exist_ok)

            def touch(self, mode=0o666, exist_ok=True):
                p = self.resolve()
                if not str(p).startswith(str(ws)):
                    rel = str(p).lstrip('/')
                    p = ws / 'files' / 'sandbox_redirects' / rel
                    p.parent.mkdir(parents=True, exist_ok=True)
                return _PathLibPath.touch(p, mode=mode, exist_ok=exist_ok)

        # Build sandboxed builtins dict
        sandboxed_builtins = {}
        for name in dir(_builtins):
            if name.startswith('_') and name not in ('__name__', '__doc__'):
                continue
            try:
                sandboxed_builtins[name] = getattr(_builtins, name)
            except AttributeError:
                pass
        sandboxed_builtins['open'] = _sandboxed_open
        sandboxed_builtins['__import__'] = _sandboxed_import

        exec_globals = {
            "__builtins__": sandboxed_builtins,
            "Path": SandboxedPath,
        }
    else:
        exec_globals = {"__builtins__": __builtins__}

    try:
        exec(code, exec_globals)
        output = sys.stdout.getvalue()
        return output if output else "(code executed, no output)"
    except Exception as e:
        return f"Code execution error: {e}"
    finally:
        sys.stdout = old_stdout


def _run_function_test(test_target: str, test_code: str,
                       timeout: int, started_at: float) -> dict:
    """Import the tool code and call main(), return result."""
    import time as _time
    from io import StringIO
    import sys as _sys
    import signal

    old_stdout = _sys.stdout
    _sys.stdout = StringIO()

    # Timeout enforcement via SIGALRM (Unix only)
    def _handle_timeout(signum, frame):
        raise TimeoutError(f"Function test exceeded {timeout}s timeout.")

    old_handler = None
    old_alarm = 0
    use_alarm = hasattr(signal, 'SIGALRM') and timeout > 0
    if use_alarm:
        old_handler = signal.signal(signal.SIGALRM, _handle_timeout)
        old_alarm = signal.alarm(int(timeout) if timeout >= 1 else 1)

    try:
        ns = {}
        exec(test_code, ns)
        func = ns.get("main") or ns.get(test_target)
        if func is None:
            candidates = {k: v for k, v in ns.items()
                          if callable(v) and not k.startswith("_") and not isinstance(v, type)}
            if candidates:
                func = list(candidates.values())[0]
        if func is None or not callable(func):
            return {
                "passed": False, "total": 1, "failures": 1,
                "errors": f"No callable function found. Defined: {list(ns.keys())}",
                "output": _sys.stdout.getvalue(),
                "duration_ms": (_time.monotonic() - started_at) * 1000,
            }
        output = func()
        stdout_output = _sys.stdout.getvalue()
        full_output = stdout_output + ("\n" + str(output) if output else "")
        return {
            "passed": True, "total": 1, "failures": 0,
            "errors": "", "output": full_output.strip() or "(no output)",
            "duration_ms": (_time.monotonic() - started_at) * 1000,
        }
    except TimeoutError:
        return {
            "passed": False, "total": 1, "failures": 1,
            "errors": f"Function test exceeded {timeout}s timeout.",
            "output": _sys.stdout.getvalue(),
            "duration_ms": (_time.monotonic() - started_at) * 1000,
        }
    except Exception as e:
        return {
            "passed": False, "total": 1, "failures": 1,
            "errors": f"{type(e).__name__}: {e}",
            "output": _sys.stdout.getvalue(),
            "duration_ms": (_time.monotonic() - started_at) * 1000,
        }
    finally:
        if use_alarm:
            signal.alarm(0)
            if old_handler is not None:
                signal.signal(signal.SIGALRM, old_handler)
        _sys.stdout = old_stdout


def _run_assert_test(test_code: str, timeout: int, started_at: float) -> dict:
    """Execute assertion code and return pass/fail."""
    import time as _time
    import signal

    def _handle_timeout(signum, frame):
        raise TimeoutError(f"Assert test exceeded {timeout}s timeout.")

    old_handler = None
    old_alarm = 0
    use_alarm = hasattr(signal, 'SIGALRM') and timeout > 0
    if use_alarm:
        old_handler = signal.signal(signal.SIGALRM, _handle_timeout)
        old_alarm = signal.alarm(int(timeout) if timeout >= 1 else 1)

    try:
        exec(test_code, {})
        return {
            "passed": True, "total": 1, "failures": 0,
            "errors": "", "output": "All assertions passed.",
            "duration_ms": (_time.monotonic() - started_at) * 1000,
        }
    except TimeoutError:
        return {
            "passed": False, "total": 1, "failures": 1,
            "errors": f"Assert test exceeded {timeout}s timeout.",
            "output": "",
            "duration_ms": (_time.monotonic() - started_at) * 1000,
        }
    except AssertionError as e:
        return {
            "passed": False, "total": 1, "failures": 1,
            "errors": f"AssertionError: {e}",
            "output": "",
            "duration_ms": (_time.monotonic() - started_at) * 1000,
        }
    except Exception as e:
        return {
            "passed": False, "total": 1, "failures": 1,
            "errors": f"{type(e).__name__}: {e}",
            "output": "",
            "duration_ms": (_time.monotonic() - started_at) * 1000,
        }
    finally:
        if use_alarm:
            signal.alarm(0)
            if old_handler is not None:
                signal.signal(signal.SIGALRM, old_handler)


def _run_pytest_test(test_target: str, test_code: str,
                     timeout: int, started_at: float,
                     workspace: "Path") -> dict:
    """Run pytest against a test file in the workspace."""
    import time as _time
    import subprocess
    import re

    test_file = workspace / test_code.lstrip("/")
    if not test_file.exists():
        return {
            "passed": False, "total": 0, "failures": 1,
            "errors": f"Test file not found: {test_file}",
            "output": "", "duration_ms": (_time.monotonic() - started_at) * 1000,
        }

    venv_dir = workspace / ".forge_venv"
    pytest_bin = venv_dir / "bin" / "pytest"
    if not pytest_bin.exists():
        return {
            "passed": False, "total": 0, "failures": 1,
            "errors": "pytest not installed in .forge_venv/. Install pytest via forge dependencies.",
            "output": "", "duration_ms": (_time.monotonic() - started_at) * 1000,
        }

    try:
        proc = subprocess.run(
            [str(pytest_bin), str(test_file), "-v"],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(workspace),
        )
        output = proc.stdout + "\n" + proc.stderr
        passed = proc.returncode == 0
        total = 0
        failures = 0
        match = re.search(r'(\d+) passed', output)
        if match:
            total += int(match.group(1))
        match = re.search(r'(\d+) failed', output)
        if match:
            failures = int(match.group(1))
            total += failures
        if total == 0:
            total = 1 if passed else 0
        return {
            "passed": passed,
            "total": total,
            "failures": failures,
            "errors": "" if passed else f"pytest exited with code {proc.returncode}",
            "output": output[:5000],
            "duration_ms": (_time.monotonic() - started_at) * 1000,
        }
    except subprocess.TimeoutExpired:
        return {
            "passed": False, "total": 0, "failures": 1,
            "errors": f"pytest exceeded {timeout}s timeout.",
            "output": "", "duration_ms": (_time.monotonic() - started_at) * 1000,
        }


def run_test(test_target: str, test_type: str = "function",
             test_code: str = "", timeout: int = 60) -> dict:
    """Run a test against a tool in the sandboxed workspace.

    Args:
        test_target: Name of the tool or test to run.
        test_type: "function" (import + call main), "pytest" (run pytest file),
                   or "assert" (run assertion code).
        test_code: Tool source code (function/assert mode) or test file path (pytest).
        timeout: Max seconds before timeout (default 60).

    Returns:
        dict with keys: passed (bool), total (int), failures (int),
             errors (str), output (str), duration_ms (float)
    """
    import time as _time
    from pathlib import Path as _PathLibPath

    started_at = _time.monotonic()
    ws = _WORKSPACE_DIR.resolve() if _WORKSPACE_DIR else _PathLibPath.cwd()

    if test_type == "function":
        return _run_function_test(test_target, test_code, timeout, started_at)
    elif test_type == "assert":
        return _run_assert_test(test_code, timeout, started_at)
    elif test_type == "pytest":
        return _run_pytest_test(test_target, test_code, timeout, started_at, ws)
    else:
        return {
            "passed": False, "total": 0, "failures": 1,
            "errors": f"Unknown test_type: {test_type}. Use 'function', 'pytest', or 'assert'.",
            "output": "", "duration_ms": (_time.monotonic() - started_at) * 1000,
        }


def resolve_storage_path(content_type: str, filename: str) -> str:
    """Resolve a semantic content type + filename to a workspace path.

    Instead of inventing your own directory structure, use this tool to get
    the canonical path for any artifact you create.

    Content types: poem, knowledge, concept, journal, reflection, report,
    milestone, commitment, goal, tool, test, note, creative, capture, letter, general.

    Examples:
      resolve_storage_path("poem", "spring.md")   → poetry/spring.md
      resolve_storage_path("knowledge", "zen.md") → knowledge/zen.md
      resolve_storage_path("journal", "2026-05.md") → journal/2026-05.md
      resolve_storage_path("report", "v0.5.0.md") → reports/v0.5.0.md
    """
    from tain_agent.core.storage_registry import resolve_content_path, get_schema_description
    ws = _WORKSPACE_DIR
    if ws is None:
        ws = Path(os.environ.get("WORKSPACE_PATH", "."))
    target = resolve_content_path(ws, content_type, filename)
    return (
        f"Resolved path: {target.relative_to(ws)}\n\n"
        f"{get_schema_description()}"
    )


def get_current_time() -> str:
    """Get the current time in the configured timezone (Asia/Shanghai)."""
    return now().isoformat()


def list_available_tools(tool_registry) -> str:
    """List all tools currently available in the registry."""
    tools = tool_registry.list_tools()
    lines = [f"Available tools ({len(tools)}):"]
    for name, info in tools.items():
        lines.append(f"  - {name}: {info['description']}")
    return "\n".join(lines)


def describe_tool(tool_registry, tool_name: str) -> str:
    """Get detailed information about a specific tool.

    Args:
        tool_registry: ToolRegistry instance.
        tool_name: Name of the tool to describe.

    Returns:
        Formatted string with tool name, description, parameters, and readonly status.
    """
    tools = tool_registry.list_tools()
    if tool_name not in tools:
        return f"Tool '{tool_name}' not found. Use list_available_tools to see all tools."
    info = tools[tool_name]
    params = info.get("parameters", {})
    param_lines = []
    if params:
        for pname, pspec in params.items():
            req = "(required)" if pspec.get("required") else "(optional)"
            param_lines.append(f"    - {pname} ({pspec.get('type', 'any')}) {req}: {pspec.get('description', '')}")
    param_str = "\n".join(param_lines) if param_lines else "    (no parameters)"
    readonly = "yes" if info.get("is_readonly") else "no"
    return (
        f"Tool: {tool_name}\n"
        f"Description: {info['description']}\n"
        f"Parameters:\n{param_str}\n"
        f"Read-only: {readonly}"
    )


# ─── Memory note tools ────────────────────────────────────────────────────

_NOTES_FILENAME = "agent_notes.jsonl"


def _get_notes_path() -> Path:
    """Get the notes file path within the agent workspace."""
    if _WORKSPACE_DIR is None:
        return Path(_NOTES_FILENAME)
    memory_dir = _WORKSPACE_DIR / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir / _NOTES_FILENAME


def remember_note(category: str = "", content: str = "", **kwargs) -> dict:
    """Record a note to persistent memory.

    Notes are stored as JSONL entries in the agent's workspace memory directory.
    Use this to save important discoveries, patterns, or user preferences
    that should persist across sessions.

    Accepts flexible parameter formats to be robust against LLM variations:
      - Flat: {\"category\": \"...\", \"content\": \"...\"}
      - Keyword: category=\"...\", content=\"...\"

    Args:
        category: Category label (e.g. 'discovery', 'user_preference', 'pattern', 'reflection').
        content: The note content to save.

    Returns:
        Confirmation with the note entry.
    """
    import json as _json

    # Handle nested/wrapped formats that LLMs sometimes produce
    if not category and not content:
        for wrapper_key in ("note", "params", "arguments", "object"):
            if wrapper_key in kwargs and isinstance(kwargs[wrapper_key], dict):
                inner = kwargs[wrapper_key]
                category = str(inner.get("category", inner.get("cat", "")))
                content = str(inner.get("content", inner.get("text", inner.get("body", ""))))
                break

    # Still empty? Try kwargs directly
    if not category:
        category = str(kwargs.get("category", kwargs.get("cat", "")))
    if not content:
        content = str(kwargs.get("content", kwargs.get("text", kwargs.get("body", ""))))

    category = category.strip().lower()
    content = content.strip()

    if not category:
        return {"status": "error", "error": "category is required", "hint": "Provide a category like 'discovery', 'user_preference', 'pattern', 'reflection', 'idea', 'decision', 'milestone'."}
    if not content:
        return {"status": "error", "error": "content is required", "hint": "Provide the note content to save."}

    note = {
        "timestamp": now().isoformat(),
        "category": category,
        "content": content,
    }

    notes_path = _get_notes_path()
    try:
        with open(notes_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(note, ensure_ascii=False) + "\n")
        return {"status": "saved", "note": note, "path": str(notes_path)}
    except IOError as e:
        return {"status": "error", "error": str(e)}


def recall_notes(category: str = "", limit: int = 20) -> dict:
    """Retrieve notes from persistent memory.

    Returns notes sorted by recency (newest first), optionally filtered
    by category.

    Args:
        category: Optional category filter. Leave empty to get all notes.
        limit: Maximum number of notes to return (default 20).

    Returns:
        List of matching notes with total count.
    """
    import json as _json

    notes_path = _get_notes_path()
    if not notes_path.exists():
        return {"notes": [], "total": 0, "message": "No notes yet. Use remember_note to create one."}

    notes = []
    try:
        for line in notes_path.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                try:
                    note = _json.loads(line)
                    if isinstance(note, dict) and "content" in note:
                        notes.append(note)
                except (_json.JSONDecodeError, ValueError):
                    continue
    except IOError:
        return {"notes": [], "total": 0, "error": "Failed to read notes file."}

    notes.sort(key=lambda n: n.get("timestamp", ""), reverse=True)

    if category:
        cat = category.strip().lower()
        notes = [n for n in notes if n.get("category", "") == cat]

    total = len(notes)
    return {"notes": notes[:limit], "total": total, "shown": min(limit, total)}


def register_primal_tools(registry, workspace_dir: str = None) -> None:
    """Register all primal tools with the given registry.

    Args:
        registry: ToolRegistry instance.
        workspace_dir: Path to agent's isolated workspace. All file I/O
                       is scoped to this directory.
    """
    global _WORKSPACE_DIR
    if workspace_dir:
        _WORKSPACE_DIR = Path(workspace_dir).resolve()
        _WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    registry.register(
        "observe_environment", observe_environment,
        "Scan YOUR isolated workspace directory. You can only see files "
        "within your own workspace — project source code is invisible to you.",
    )
    registry.register(
        "explore_directory", explore_directory,
        "Recursively list files and directories within YOUR workspace. "
        "You cannot explore outside your workspace.",
        {"path": {"type": "string", "description": "Path within your workspace.", "required": False}},
    )
    registry.register(
        "read_file", read_file,
        "Read a file from YOUR workspace. You can only read files inside "
        "your isolated workspace. Project source code is not accessible.",
        {"path": {"type": "string", "description": "Path within your workspace.", "required": True}},
    )
    registry.register(
        "write_file", write_file,
        "Write content to a file in YOUR workspace. All your products, "
        "knowledge, and creations must live here. You CANNOT modify project source.",
        {
            "path": {"type": "string", "description": "Path within your workspace to write to.", "required": True},
            "content": {"type": "string", "description": "Content to write.", "required": True},
        },
    )
    registry.register(
        "web_fetch", web_fetch,
        "Fetch content from a URL. Use this to read web pages, APIs, or any HTTP resource.",
        {"url": {"type": "string", "description": "The URL to fetch.", "required": True}},
    )
    registry.register(
        "web_search", web_search,
        "Search the internet using DuckDuckGo. Returns titles, URLs, and snippets.",
        {
            "query": {"type": "string", "description": "Search query.", "required": True},
            "max_results": {
                "type": "integer", "description": "Max number of results.", "required": False,
            },
        },
    )
    registry.register(
        "execute_code", execute_code,
        "Execute Python code and return its output. Use this to compute, test, or create new capabilities.",
        {
            "code": {"type": "string", "description": "Python code to execute.", "required": True},
            "timeout": {"type": "integer", "description": "Max seconds.", "required": False},
        },
    )
    registry.register(
        "get_current_time", get_current_time,
        "Get the current UTC time in ISO 8601 format.",
    )
    registry.register(
        "resolve_storage_path", resolve_storage_path,
        "Get the canonical workspace path for a content type. "
        "Use this whenever you write files — instead of inventing your own "
        "directory structure. Content types: poem, knowledge, concept, "
        "journal, reflection, report, milestone, commitment, goal, tool, "
        "test, note, creative, capture, letter, general.",
        {
            "content_type": {
                "type": "string",
                "description": "Semantic content type (e.g. poem, knowledge, journal, report).",
                "required": True,
            },
            "filename": {
                "type": "string",
                "description": "The filename to write (e.g. spring.md).",
                "required": True,
            },
        },
    )
    registry.register(
        "remember_note", remember_note,
        "Save a note to your persistent memory. Notes survive across sessions "
        "and can be recalled later. Use this to record important discoveries, "
        "user preferences, patterns you've noticed, or reflections on your evolution. "
        "Categories help organize: discovery, user_preference, pattern, reflection, "
        "idea, decision, milestone.",
        {
            "category": {
                "type": "string",
                "description": "Category label (e.g. discovery, user_preference, pattern, reflection).",
                "required": True,
            },
            "content": {
                "type": "string",
                "description": "The note content to save.",
                "required": True,
            },
        },
    )
    registry.register(
        "recall_notes", recall_notes,
        "Retrieve notes from your persistent memory. Returns notes sorted "
        "by recency (newest first). Filter by category or get all notes. "
        "Use this to recall what you've learned, user preferences, or past discoveries.",
        {
            "category": {
                "type": "string",
                "description": "Optional category filter. Leave empty to get all notes.",
                "required": False,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum notes to return (default 20).",
                "required": False,
            },
        },
    )
    # Tool discovery — let agent query its own capabilities at runtime
    registry.register(
        "list_available_tools", lambda **kw: list_available_tools(registry),
        "List all tools currently available to you. Use this when you need "
        "to know what capabilities you have at runtime.",
    )
    registry.register(
        "describe_tool", lambda tool_name, **kw: describe_tool(registry, tool_name),
        "Get detailed information about a specific tool including its parameters "
        "and whether it is read-only.",
        {"tool_name": {"type": "string", "description": "Name of the tool to describe.", "required": True}},
    )
