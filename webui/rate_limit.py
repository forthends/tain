"""Token bucket rate limiter per client IP."""
import time
from collections import defaultdict
from fastapi import Request, HTTPException


class TokenBucket:
    def __init__(self, rate: int = 60, per_seconds: float = 60.0):
        self.rate = rate
        self.per_seconds = per_seconds
        self.tokens = float(rate)
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(float(self.rate), self.tokens + elapsed * (self.rate / self.per_seconds))
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


_buckets: dict[str, TokenBucket] = defaultdict(lambda: TokenBucket(rate=60))


def check_rate_limit(client_ip: str) -> bool:
    return _buckets[client_ip].consume()


async def rate_limit_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/") and "chat" in request.url.path:
        client_ip = request.client.host if request.client else "unknown"
        if not check_rate_limit(client_ip):
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
    return await call_next(request)
