"""Application entrypoint.

Run with: uvicorn app.main:app --reload
"""

import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import health, pages, review
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging

APP_DIR = Path(__file__).resolve().parent


def _warm_up_embeddings() -> None:
    """Pre-load the embedding model so the first review isn't slow.

    Runs in a daemon thread: startup stays fast, and a failure here only
    means the first review pays the load cost instead.
    """
    from app.services.vector_service import VectorService

    logger = get_logger("startup")
    try:
        VectorService._get_embedder()
    except Exception:
        logger.exception("Embedding warm-up failed; first review will retry")


def create_app() -> FastAPI:
    setup_logging()
    get_settings()  # fail fast on missing/invalid configuration

    app = FastAPI(
        title="AI Code Review Dashboard",
        version="1.0.0",
        description=(
            "Multi-agent AI code review: submit a public repository URL and a "
            "roles PDF, get structured findings, scores, and a report."
        ),
    )

    app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

    app.include_router(pages.router)
    app.include_router(health.router)
    app.include_router(review.router)

    threading.Thread(target=_warm_up_embeddings, daemon=True).start()
    return app


app = create_app()
