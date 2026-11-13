"""NexusRaid API entry point.

Run from the backend/ folder:
    uvicorn app.main:app --reload

Development: the React dev server (port 5173) calls this API on port 8000.
Single-port mode: after `npm run build` in frontend/, this server also serves
the built dashboard, so http://<host>:8000 opens the whole application.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import analysis, datasets, health, monitoring, reports, system
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.database.connection import SessionLocal, init_db

API_PREFIX = "/api/v1"
logger = logging.getLogger("nexusraid")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once at startup, before the first request is served.
    settings = get_settings()
    settings.ensure_directories()
    init_db()
    with SessionLocal() as db:
        datasets.purge_expired(db, settings)
    if settings.environment == "production" and not settings.access_key:
        logger.warning("Running in production without NEXUSRAID_ACCESS_KEY: anyone who can reach this "
                       "server can upload and read datasets.")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Dataset analysis, anomaly detection and early-warning platform.",
        lifespan=lifespan,
    )

    # Only the frontend origins listed in settings may call the API from a browser.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Access-Key"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    register_error_handlers(app)
    for module in (health, system, datasets, analysis, reports, monitoring):
        app.include_router(module.router, prefix=API_PREFIX)

    # Single-port mode: serve the built React app if it exists. Registered last,
    # so every /api/v1 route above takes priority.
    if (settings.frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
    return app


app = create_app()
