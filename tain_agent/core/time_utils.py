"""
Time Utilities — 时间工具

Centralized timezone-aware datetime helpers.
Configured via config.yaml → agent.timezone (default: Asia/Shanghai).

Usage:
    from tain_agent.core.time_utils import now
    timestamp = now().isoformat()
"""

from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

_tz = ZoneInfo("Asia/Shanghai")  # default — can be changed via set_timezone()


def set_timezone(name: str) -> None:
    """Set the agent-wide timezone. Accepts IANA names like 'Asia/Shanghai', 'UTC', etc."""
    global _tz
    _tz = ZoneInfo(name)


def get_timezone() -> ZoneInfo:
    """Return the current agent-wide timezone."""
    return _tz


def now() -> datetime:
    """Return current datetime in the configured timezone."""
    return datetime.now(_tz)
