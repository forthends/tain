"""API Key authentication middleware for Web UI."""
import os
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware


class APIKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_key: str = ""):
        super().__init__(app)
        self._key = api_key or os.environ.get("TAIN_API_KEY", "")

    async def dispatch(self, request: Request, call_next):
        if not self._key:
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            key = request.headers.get("X-API-Key", "")
            if not key or key != self._key:
                raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return await call_next(request)
