from app.core.database import engine
from app.services.annotation_export_job_service import (
    ANNOTATION_EXPORT_JOB_TYPE,
    run_annotation_export_job,
)
from app.services.annotation_import_job_service import (
    LABELME_IMPORT_JOB_TYPE,
    LABELME_IMPORT_ROLLBACK_JOB_TYPE,
    run_labelme_import_job,
    run_labelme_import_rollback_job,
)
from app.services.database_backup_service import (
    DATABASE_BACKUP_JOB_TYPE,
    run_database_backup_job,
)
from app.services.scan_job_service import SCAN_JOB_TYPE, run_scan_job
from app.services.metadata_import_job_service import (
    METADATA_IMPORT_JOB_TYPE,
    METADATA_IMPORT_ROLLBACK_JOB_TYPE,
    run_metadata_import_job,
    run_metadata_import_rollback_job,
)
from app.services.thumbnail_job_service import THUMBNAIL_JOB_TYPE, run_thumbnail_job
from app.services.thumbnail_maintenance_service import (
    THUMBNAIL_MAINTENANCE_JOB_TYPE,
    run_thumbnail_maintenance_job,
)
from app.services.job_runner import JobRunner


job_runner = JobRunner(engine)
job_runner.register_handler(SCAN_JOB_TYPE, run_scan_job)
job_runner.register_handler(METADATA_IMPORT_JOB_TYPE, run_metadata_import_job)
job_runner.register_handler(
    METADATA_IMPORT_ROLLBACK_JOB_TYPE,
    run_metadata_import_rollback_job,
)
job_runner.register_handler(ANNOTATION_EXPORT_JOB_TYPE, run_annotation_export_job)
job_runner.register_handler(LABELME_IMPORT_JOB_TYPE, run_labelme_import_job)
job_runner.register_handler(
    LABELME_IMPORT_ROLLBACK_JOB_TYPE,
    run_labelme_import_rollback_job,
)
job_runner.register_handler(THUMBNAIL_JOB_TYPE, run_thumbnail_job)
job_runner.register_handler(
    THUMBNAIL_MAINTENANCE_JOB_TYPE,
    run_thumbnail_maintenance_job,
)
job_runner.register_handler(DATABASE_BACKUP_JOB_TYPE, run_database_backup_job)
