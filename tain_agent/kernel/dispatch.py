"""Event dispatch — routes cross-plugin calls through the Kernel."""

from __future__ import annotations
from typing import Any, Callable
import logging

logger = logging.getLogger(__name__)


class RouteNotFound(Exception):
    """Raised when no handler is registered for a dispatch event."""
    def __init__(self, event: str):
        super().__init__(f"No handler registered for route: {event}")
        self.event = event


class Dispatch:
    """Typed event router. Plugins never import each other — they call dispatch()."""

    def __init__(self):
        self._routes: dict[str, Callable] = {}

    def register(self, event: str, handler: Callable) -> None:
        if event in self._routes:
            logger.warning("Dispatch route %r overwritten", event)
        self._routes[event] = handler

    def call(self, event: str, *args: Any, **kwargs: Any) -> Any:
        handler = self._routes.get(event)
        if handler is None:
            raise RouteNotFound(event)
        try:
            return handler(*args, **kwargs)
        except Exception as exc:
            logger.exception("Dispatch %r failed", event)
            return f"[Dispatch Error] {event}: {exc}"

    def call_or_none(self, event: str, *args: Any, **kwargs: Any) -> Any:
        """Call a route, returning None if no handler registered (old semantics)."""
        try:
            return self.call(event, *args, **kwargs)
        except RouteNotFound:
            return None
