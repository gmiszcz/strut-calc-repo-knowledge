"""FastAPI entry point for the knowledge-assistant web app.

Mounts the AI SSE router under ``/api`` and, when a built frontend exists at
``app/dist``, serves it as the SPA. In dev the Vite server proxies ``/api`` here.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.ai_router import router as ai_router
from app.config import get_web_settings
from app.history import router as history_router

logger = logging.getLogger(__name__)

DIST_DIR = Path(__file__).resolve().parent / "dist"


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Returns:
        The configured app.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_web_settings()

    app = FastAPI(title="StrutCalc knowledge assistant", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.include_router(ai_router, prefix="/api")
    app.include_router(history_router, prefix="/api")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        """Liveness probe.

        Returns:
            A small status object.
        """
        return {"status": "ok"}

    if DIST_DIR.is_dir():
        app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="spa")
        logger.info("dist=<%s> | serving built frontend", DIST_DIR)
    else:
        logger.info("no built frontend at %s — run the Vite dev server", DIST_DIR)

    return app


app = create_app()
