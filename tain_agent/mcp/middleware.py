from __future__ import annotations
import time
from collections import defaultdict

class ProductionGateMiddleware:
    def check(self, readiness: dict) -> bool:
        return readiness.get("status") == "production_ready"

class RateLimiter:
    def __init__(self, max_per_minute: int = 60):
        self._max = max_per_minute
        self._windows: dict[str, list[float]] = defaultdict(list)
    def allow(self, endpoint: str) -> bool:
        now = time.time()
        window = self._windows[endpoint]
        window[:] = [t for t in window if now - t < 60.0]
        if len(window) >= self._max:
            return False
        window.append(now)
        return True
