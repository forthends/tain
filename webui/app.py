"""Web UI for Tain Agent Framework — FastAPI application."""

from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from tain_agent import __version__

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def create_app() -> FastAPI:
    app = FastAPI(title="Tain Agent Framework — Web UI", version=__version__)

    # Security middleware
    from webui.auth import APIKeyMiddleware
    from webui.rate_limit import rate_limit_middleware
    app.add_middleware(APIKeyMiddleware)
    app.middleware("http")(rate_limit_middleware)

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from webui.routes.pages import router as pages_router
    from webui.routes.api_agents import router as api_agents_router
    from webui.routes.api_chat import router as api_chat_router

    app.include_router(pages_router)
    app.include_router(api_agents_router, prefix="/api")
    app.include_router(api_chat_router, prefix="/api")

    return app
