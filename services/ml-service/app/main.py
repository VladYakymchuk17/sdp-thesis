import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.routes import router, get_ensemble
from app.config import settings
from app.db.session import init_db
from app.pipeline.orchestrator import reap_orphaned_jobs

logging.basicConfig(
    level=logging.INFO if settings.debug else logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting %s ...", settings.app_name)
    try:
        init_db()
    except Exception as e:
        logger.warning("Database not ready: %s", e)
    try:
        ensemble = get_ensemble()
        logger.info("Ensemble loaded: %d models", len(ensemble.models))
    except Exception as e:
        logger.warning("Models not loaded at startup: %s", e)
    try:
        reap_orphaned_jobs()
    except Exception as e:
        logger.warning("Could not reconcile previous jobs: %s", e)
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Software Defect Prediction service for TypeScript projects. "
                "Uses ensemble of ML models with SHAP explainability.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health_check() -> dict:
    return {"status": "ok", "service": settings.app_name}
