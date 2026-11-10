from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    annotation_classes,
    annotation_exports,
    annotations,
    browse,
    batch_reception,
    comparison,
    dataset_card,
    datasets,
    daily_tools,
    delivery_checklist,
    directory_exports,
    industrial,
    validation,
    filesystem,
    jobs,
    organization,
    samples,
    sample_collections,
    sam,
    system,
    triage,
    triage_directory_mapping,
    workpiece,
)
from app.core.config import get_settings
from app.core.database import init_db
from app.core.job_runtime import job_runner
from app.core.portable import portable_controller
from app.core.static_frontend import install_frontend


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

app = FastAPI(title=settings.app_name, version="0.5.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(datasets.router)
app.include_router(daily_tools.router)
app.include_router(batch_reception.router)
app.include_router(delivery_checklist.router)
app.include_router(organization.router)
app.include_router(browse.router)
app.include_router(dataset_card.router)
app.include_router(comparison.router)
app.include_router(industrial.router)
app.include_router(validation.router)
app.include_router(directory_exports.router)
app.include_router(filesystem.router)
app.include_router(samples.router)
app.include_router(sample_collections.router)
app.include_router(annotations.router)
app.include_router(sam.router)
app.include_router(annotation_classes.router)
app.include_router(annotation_exports.router)
app.include_router(system.router)
app.include_router(jobs.router)
app.include_router(triage.router)
app.include_router(triage_directory_mapping.router)
app.include_router(workpiece.router)


@app.get("/health")
def health_check() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "application": "dataset-manager",
        "portable": bool(portable_controller.describe()["enabled"]),
    }


install_frontend(app)
