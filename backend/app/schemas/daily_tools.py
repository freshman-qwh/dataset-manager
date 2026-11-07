"""Read-only helpers for finding registered images and inspecting coverage."""
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.sample import SampleRead

CoverageStatus = Literal["all", "normal", "anomaly", "pending", "untriaged", "stale", "unavailable"]
LookupEntry = Annotated[str, Field(max_length=2000)]


class FilenameLookupRequest(BaseModel):
    entries: list[LookupEntry] = Field(min_length=1, max_length=500)


class LookupCandidate(BaseModel):
    id: int
    filename: str
    relative_path: str
    absolute_path: str
    file_status: str
    file_hash: str


class FilenameLookupResult(BaseModel):
    entry: str
    total: int
    candidates: list[LookupCandidate]
    page: int = 1
    page_size: int


class FilenameLookupRead(BaseModel):
    dataset_id: int
    duplicate_count: int
    blank_count: int
    results: list[FilenameLookupResult]


class CoverageAxis(BaseModel):
    id: int | None
    name: str


class CoverageCounts(BaseModel):
    total: int = 0
    normal: int = 0
    anomaly: int = 0
    pending: int = 0
    untriaged: int = 0
    stale: int = 0
    unavailable: int = 0


class CoverageCell(CoverageCounts):
    category_id: int | None
    batch_id: int | None


class CoverageRead(BaseModel):
    dataset_id: int
    categories: list[CoverageAxis]
    batches: list[CoverageAxis]
    cells: list[CoverageCell]
    totals: CoverageCounts


class CoverageSamplesRead(BaseModel):
    items: list[SampleRead]
    total: int
    page: int
    page_size: int
