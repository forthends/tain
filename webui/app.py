"""Web UI for Tain Agent Framework — FastAPI application."""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from tain_agent import __version__

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    from webui.streaming import cancel_all_streams
    cancel_all_streams()


def create_app() -> FastAPI:
    app = FastAPI(title="Tain Agent Framework — Web UI", version=__version__,
                  lifespan=lifespan)

    # Security middleware
    from webui.auth import APIKeyMiddleware
    from webui.rate_limit import rate_limit_middleware, configure_rate_limits

    # Read chat rate limit from config (default: 60 req/min)
    try:
        import yaml
        with open(PROJECT_ROOT / "config.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        rate = cfg.get("webui", {}).get("chat_rate_limit_per_minute", 60)
    except Exception:
        rate = 60
    configure_rate_limits(rate)

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
