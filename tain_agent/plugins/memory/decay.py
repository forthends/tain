"""Memory decay engine — importance-based forgetting with recall boost."""

import math
from datetime import datetime, timezone


def _days_since(iso_timestamp: str) -> float:
    try:
        created = datetime.fromisoformat(iso_timestamp)
        now = datetime.now(timezone.utc)
        return max(0.0, (now - created).total_seconds() / 86400.0)
    except Exception:
        return 0.0


def decay_rate(importance: float) -> float:
    return max(0.01, 0.30 * (1.0 - importance))


def boost_factor(last_recalled_at: str | None) -> float:
    if last_recalled_at is None:
        return 1.0
    days = _days_since(last_recalled_at)
    return max(1.0, 2.0 * math.exp(-0.7 * days))


def current_strength(importance: float, created_at: str,
                     recall_count: int, last_recalled_at: str | None = None) -> float:
    days = _days_since(created_at)
    dr = decay_rate(importance)
    base = importance * math.exp(-dr * days)
    recall_bonus = 1.0 + math.log(1 + recall_count) * 0.1
    boost = boost_factor(last_recalled_at)
    return round(base * recall_bonus * boost, 6)


def should_forget(strength: float, threshold: float = 0.05) -> bool:
    return strength < threshold
