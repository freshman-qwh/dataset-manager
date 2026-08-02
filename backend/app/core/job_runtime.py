from app.core.database import engine
from app.services.annotation_export_job_service import (
    ANNOTATION_EXPORT_JOB_TYPE,
    run_annotation_export_job,
)
from app.services.scan_job_service import SCAN_JOB_TYPE, run_scan_job
from app.services.thumbnail_job_service import THUMBNAIL_JOB_TYPE, run_thumbnail_job
from app.services.thumbnail_maintenance_service import (
    THUMBNAIL_MAINTENANCE_JOB_TYPE,
    run_thumbnail_maintenance_job,
)
from app.services.job_runner import JobRunner


job_runner = JobRunner(engine)
job_runner.register_handler(SCAN_JOB_TYPE, run_scan_job)
job_runner.register_handler(ANNOTATION_EXPORT_JOB_TYPE, run_annotation_export_job)
job_runner.register_handler(THUMBNAIL_JOB_TYPE, run_thumbnail_job)
job_runner.register_handler(
    THUMBNAIL_MAINTENANCE_JOB_TYPE,
    run_thumbnail_maintenance_job,
)
