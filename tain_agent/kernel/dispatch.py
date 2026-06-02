"""Event dispatch — routes cross-plugin calls through the Kernel."""

from __future__ import annotations
from typing import Any, Callable
import logging

logger = logging.getLogger(__name__)


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
            logger.debug("Dispatch: no handler for %r", event)
            return None
        try:
            return handler(*args, **kwargs)
        except Exception as exc:
            logger.exception("Dispatch %r failed", event)
            return f"[Dispatch Error] {event}: {exc}"
