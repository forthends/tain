"""TriggerManager — time-based and event-based evaluation triggers."""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

EVENT_TRIGGERS = {
    "tool.forge.success": {"count": 1},
    "tool.forge.failure": {"count": 3},
    "skill.maturity.upgrade": {"count": 1},
    "skill.success_rate_below_0.3": {"count": 1},
    "identity.autonomy.change": {"count": 1},
    "collaboration.teach.complete": {"count": 1},
}


class TriggerManager:
    """Tracks cycles and events to decide when to run evaluations."""

    def __init__(self, routine_interval: int = 50, deep_interval: int = 200):
        self.routine_interval = routine_interval
        self.deep_interval = deep_interval
        self._cycle = 0
        self._should_run_routine = False
        self._should_run_deep = False
        self._triggered_by_event: str | None = None
        self._event_counters: dict[str, int] = {}

    def on_cycle(self, cycle: int) -> None:
        """Called each PRAL cycle to check time-based triggers."""
        self._cycle = cycle
        if cycle % self.routine_interval == 0:
            self._should_run_routine = True
        if cycle % self.deep_interval == 0:
            self._should_run_deep = True

    def on_event(self, event: str, count: int = 1) -> None:
        """Record an event occurrence. Triggers evaluation if threshold met."""
        prev = self._event_counters.get(event, 0)
        current = prev + count
        self._event_counters[event] = current

        threshold = EVENT_TRIGGERS.get(event, {}).get("count", 999)
        if current >= threshold:
            self._should_run_routine = True
            self._triggered_by_event = event
            self._event_counters[event] = 0
            logger.info("Event trigger: %s (count=%d)", event, current)

    @property
    def should_run_routine(self) -> bool:
        return self._should_run_routine

    @property
    def should_run_deep(self) -> bool:
        return self._should_run_deep

    @property
    def triggered_by(self) -> str | None:
        return self._triggered_by_event or ("cycle" if self._should_run_routine else None)

    def is_event_trigger(self, event: str, count: int = 1) -> bool:
        """Check if a given event count would trigger evaluation."""
        threshold = EVENT_TRIGGERS.get(event, {}).get("count", 999)
        return count >= threshold

    def consume(self) -> dict:
        """Return current trigger state and reset flags."""
        result = {
            "routine": self._should_run_routine,
            "deep": self._should_run_deep,
            "triggered_by": self.triggered_by,
        }
        self._should_run_routine = False
        self._should_run_deep = False
        self._triggered_by_event = None
        return result
