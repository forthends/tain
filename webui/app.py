"""Web UI for Tain Agent Framework — FastAPI application."""

from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def create_app() -> FastAPI:
    app = FastAPI(title="Tain Agent Framework — Web UI", version="0.4.3")

    from webui.routes.pages import router as pages_router
    from webui.routes.api_agents import router as api_agents_router
    from webui.routes.api_chat import router as api_chat_router

    app.include_router(pages_router)
    app.include_router(api_agents_router, prefix="/api")
    app.include_router(api_chat_router, prefix="/api")

    return app
