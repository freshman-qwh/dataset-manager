from pydantic import BaseModel, Field

from app.schemas.job import JobRead


class ThumbnailJobRequest(BaseModel):
    sample_ids: list[int] = Field(min_length=1, max_length=200)


class ThumbnailJobCreateResponse(BaseModel):
    job: JobRead | None = None
    created: bool
    requested_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    cached_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
