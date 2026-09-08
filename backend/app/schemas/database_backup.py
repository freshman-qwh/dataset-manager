from pydantic import BaseModel

from app.schemas.job import JobRead


class DatabaseBackupJobCreateResponse(BaseModel):
    job: JobRead
    created: bool
