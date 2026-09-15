from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    annotation_classes,
    annotation_exports,
    annotations,
    datasets,
    filesystem,
    jobs,
    samples,
    system,
    triage,
)
from app.core.config import get_settings
from app.core.database import init_db
from app.core.job_runtime import job_runner


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize local storage and SQLite tables before serving requests."""
    init_db()
    job_runner.start()
    try:
        yield
    finally:
        job_runner.stop()


settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.4.1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(datasets.router)
app.include_router(filesystem.router)
app.include_router(samples.router)
app.include_router(annotations.router)
app.include_router(annotation_classes.router)
app.include_router(annotation_exports.router)
app.include_router(system.router)
app.include_router(jobs.router)
app.include_router(triage.router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
