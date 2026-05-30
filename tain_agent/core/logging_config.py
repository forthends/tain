"""
Structured logging configuration for the Tain Agent Framework.

Provides:
  - Colored console output (preserving emoji-based UX)
  - JSONL file logging for machine-parseable structured logs
  - Per-module logger retrieval via get_logger()

Usage:
    from tain_agent.core.logging_config import get_logger
    log = get_logger(__name__)
    log.agent("agent started", agent_name="poet", phase="bootstrap")
    log.warning("rate limit approaching", reset_time="2026-01-01T00:00:00Z")
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Custom log level between INFO (20) and WARNING (30) for agent lifecycle events
AGENT_LEVEL = 23
logging.addLevelName(AGENT_LEVEL, "AGENT")


class AgentLifecycleLogger(logging.Logger):
    """Logger subclass with structured-context convenience methods.

    Standard logging methods (info, warning, error) accept **kwargs
    which are captured as structured context in the JSONL output.
    """

    def _log_with_context(self, level: int, msg: str, kwargs: dict) -> None:
        """Internal: route structured kwargs through the extra parameter."""
        self.log(level, msg, extra={"structured": kwargs})

    def agent(self, msg: str, **kwargs) -> None:
        """Log an agent lifecycle event with structured context."""
        self._log_with_context(AGENT_LEVEL, msg, kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        """Log INFO with optional structured context kwargs."""
        if kwargs:
            self._log_with_context(logging.INFO, msg, kwargs)
        else:
            super().info(msg, *args)

    def warning(self, msg: str, *args, **kwargs) -> None:
        """Log WARNING with optional structured context kwargs."""
        if kwargs:
            self._log_with_context(logging.WARNING, msg, kwargs)
        else:
            super().warning(msg, *args)

    def error(self, msg: str, *args, **kwargs) -> None:
        """Log ERROR with optional structured context kwargs."""
        if kwargs:
            self._log_with_context(logging.ERROR, msg, kwargs)
        else:
            super().error(msg, *args)

    def debug(self, msg: str, *args, **kwargs) -> None:
        """Log DEBUG with optional structured context kwargs."""
        if kwargs:
            self._log_with_context(logging.DEBUG, msg, kwargs)
        else:
            super().debug(msg, *args)


logging.setLoggerClass(AgentLifecycleLogger)


# ─── JSONL File Handler ────────────────────────────────────────────────

class JSONLHandler(logging.Handler):
    """Writes log records as JSONL for machine parsing."""

    def __init__(self, log_dir: str):
        super().__init__()
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / "agent.jsonl"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "timestamp": datetime.fromtimestamp(
                    record.created, tz=timezone.utc
                ).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "module": record.module,
                "line": record.lineno,
            }
            # Include structured context if present
            structured = getattr(record, "structured", None)
            if structured:
                entry["context"] = structured
            # Include exception info if present
            if record.exc_info and record.exc_info[1]:
                entry["exception"] = str(record.exc_info[1])

            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            self.handleError(record)


# ─── Colored Console Formatter ─────────────────────────────────────────

class ConsoleFormatter(logging.Formatter):
    """Formatter that preserves emoji prefix while adding level and module info."""

    # ANSI color codes
    COLORS = {
        "AGENT": "\033[36m",    # cyan
        "DEBUG": "\033[90m",    # grey
        "INFO": "\033[0m",      # default
        "WARNING": "\033[33m",  # yellow
        "ERROR": "\033[31m",    # red
        "CRITICAL": "\033[35m", # magenta
    }
    RESET = "\033[0m"
    DIM = "\033[2m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        msg = record.getMessage()

        # If message already has emoji prefix, keep it as-is
        # Add dimmed module:line suffix for debugging
        suffix = f"{self.DIM}  [{record.module}:{record.lineno}]{self.RESET}"

        if record.levelno <= logging.DEBUG:
            return f"{color}{msg}{suffix}{self.RESET}"
        elif record.levelno >= logging.ERROR:
            return f"{color}{msg}{suffix}{self.RESET}"
        else:
            # For INFO/AGENT level, keep the existing emoji-based format clean
            return f"{msg}"


# ─── Module-level state ────────────────────────────────────────────────

_log_initialized = False
_log_dir: Optional[str] = None


def setup_logging(log_dir: str = "agent_workspace/_logs",
                  console_level: int = logging.INFO,
                  file_level: int = logging.DEBUG) -> None:
    """Initialize structured logging for the framework.

    Call once at agent startup. Subsequent get_logger() calls return
    properly configured loggers.

    Args:
        log_dir: Directory for JSONL log files.
        console_level: Minimum level for console output.
        file_level: Minimum level for JSONL file output.
    """
    global _log_initialized, _log_dir
    _log_dir = log_dir

    root = logging.getLogger("tain_agent")
    root.setLevel(logging.DEBUG)

    # Console handler — user-facing, emoji-preserving
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(console_level)
    console.setFormatter(ConsoleFormatter())
    root.addHandler(console)

    # JSONL handler — machine-parseable structured logs
    jsonl = JSONLHandler(log_dir)
    jsonl.setLevel(file_level)
    root.addHandler(jsonl)

    _log_initialized = True


def get_logger(name: str) -> AgentLifecycleLogger:
    """Get a logger for the given module name.

    Automatically strips the 'tain_agent.' prefix for cleaner names.
    """
    if name.startswith("tain_agent."):
        name = name[len("tain_agent."):]
    logger = logging.getLogger(f"tain_agent.{name}")
    if not _log_initialized:
        # Auto-initialize with defaults if not explicitly configured
        setup_logging()
    return logger  # type: ignore[return-value]
