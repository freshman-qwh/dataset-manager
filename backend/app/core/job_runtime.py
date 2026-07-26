from app.core.database import engine
from app.services.job_runner import JobRunner


job_runner = JobRunner(engine)
