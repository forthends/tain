"""Shared sandbox allowlist — single source of truth for forge_tool and execute_code."""

SANDBOX_ALLOWED_MODULES = frozenset({
    "json", "datetime", "pathlib", "typing", "hashlib", "math",
    "collections", "itertools", "functools", "textwrap", "re", "string",
    "dataclasses", "enum", "uuid", "statistics", "csv", "base64",
    "copy", "random", "html", "xml", "argparse", "logging",
    "urllib.parse",  # was allowed in execute_code but not in forge_tool
})

SANDBOX_BLACKLIST_CALLS = frozenset({
    "eval", "exec", "compile", "__import__", "open",
})

SANDBOX_BLACKLIST_MODULES = frozenset({
    "os", "sys", "subprocess", "shutil", "socket", "ctypes",
    "multiprocessing", "signal", "builtins", "importlib",
    "urllib", "http", "ftplib", "smtplib", "telnetlib",
    "requests", "pdb", "code", "traceback", "inspect",
    "pip", "setuptools", "pkg_resources",
})


def get_allowlist() -> dict:
    """Return the sandbox allowlist and blacklist for Agent visibility."""
    return {
        "allowed_modules": sorted(SANDBOX_ALLOWED_MODULES),
        "blacklisted_calls": sorted(SANDBOX_BLACKLIST_CALLS),
        "blacklisted_modules": sorted(SANDBOX_BLACKLIST_MODULES),
    }
