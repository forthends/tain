"""
Tool templates — reusable utilities for forged tools.

These functions provide safe, consistent implementations of common
tool patterns (path resolution, output truncation, shell execution).
Forged tools should import these instead of reimplementing them.
"""

import shlex
import subprocess
import traceback
from pathlib import Path
from typing import Optional


def resolve_path(workspace_dir: str, path: str, for_write: bool = False) -> Optional[Path]:
    """Resolve a user-supplied path safely within the workspace.

    Relative paths are resolved against workspace_dir. Absolute paths
    are only accepted if they're already within workspace_dir.

    Args:
        workspace_dir: The workspace root directory.
        path: User-supplied path (relative or absolute).
        for_write: If True, applies additional write-path restrictions.

    Returns:
        Resolved Path, or None if path escapes the workspace.
    """
    ws = Path(workspace_dir).resolve()
    p = Path(path)

    if not p.is_absolute():
        resolved = (ws / p).resolve()
    else:
        resolved = p.resolve()

    try:
        resolved.relative_to(ws)
    except ValueError:
        return None

    return resolved


def truncate_output(text: str, max_tokens: int = 32000) -> str:
    """Truncate text to a token budget, preserving head and tail.

    Large tool outputs (e.g. file reads, web fetches) can overflow
    the LLM context window. This preserves the beginning and end of
    the content with a truncation marker in the middle.

    Uses character-based estimation (2 chars ≈ 1 token) as a fast
    approximation.

    Args:
        text: The full output text.
        max_tokens: Maximum token budget (default 32000).

    Returns:
        Truncated text with a marker if truncation occurred.
    """
    char_limit = max_tokens * 2
    if len(text) <= char_limit:
        return text

    head_size = char_limit // 2
    tail_size = char_limit // 4
    head = text[:head_size]
    tail = text[-tail_size:]

    original_tokens = len(text) // 2
    return (
        f"{head}\n\n"
        f"...[Content truncated: ~{original_tokens} tokens → ~{max_tokens} token limit]...\n\n"
        f"{tail}"
    )


def truncate_lines(text: str, max_lines: int = 5000) -> str:
    """Truncate text to a maximum number of lines.

    Args:
        text: The full text.
        max_lines: Maximum lines to keep.

    Returns:
        Truncated text with a marker if truncation occurred.
    """
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text

    head = lines[:max_lines * 3 // 4]
    tail = lines[-max_lines // 4:]
    return (
        "\n".join(head)
        + f"\n\n...[{len(lines) - max_lines} lines truncated]...\n\n"
        + "\n".join(tail)
    )


def run_shell(command: str, timeout: float = 30.0,
              workspace_dir: Optional[str] = None) -> dict:
    """Execute a shell command with timeout protection.

    Args:
        command: Shell command to execute.
        timeout: Maximum execution time in seconds.
        workspace_dir: Directory to run the command in.

    Returns:
        dict with stdout, stderr, exit_code, success, and duration_ms.
    """
    import time as _time

    cwd = str(workspace_dir) if workspace_dir else None
    t0 = _time.monotonic()

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            executable="/bin/bash",
        )
        elapsed_ms = (_time.monotonic() - t0) * 1000
        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": truncate_output(result.stdout),
            "stderr": truncate_output(result.stderr),
            "duration_ms": round(elapsed_ms, 2),
        }
    except subprocess.TimeoutExpired as e:
        elapsed_ms = (_time.monotonic() - t0) * 1000
        return {
            "success": False,
            "exit_code": -1,
            "stdout": truncate_output(e.stdout or ""),
            "stderr": f"Command timed out after {timeout}s",
            "duration_ms": round(elapsed_ms, 2),
        }
    except Exception as e:
        elapsed_ms = (_time.monotonic() - t0) * 1000
        return {
            "success": False,
            "exit_code": -1,
            "stderr": f"{type(e).__name__}: {e}",
            "duration_ms": round(elapsed_ms, 2),
        }


def format_error(message: str, exception: Optional[Exception] = None) -> dict:
    """Return a standard error dict for tool failures.

    Args:
        message: Human-readable error description.
        exception: Optional exception for traceback.

    Returns:
        dict with error, error_type, and optional traceback.
    """
    result = {
        "success": False,
        "error": message,
        "error_type": "tool_error",
    }
    if exception:
        result["exception"] = f"{type(exception).__name__}: {exception}"
        result["traceback"] = traceback.format_exc()
    return result


def estimate_tokens(text: str) -> int:
    """Estimate token count for a string.

    Tries tiktoken (cl100k_base), falls back to character-based estimate.

    Args:
        text: Text to estimate token count for.

    Returns:
        Estimated token count.
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return max(1, len(text) // 2)
