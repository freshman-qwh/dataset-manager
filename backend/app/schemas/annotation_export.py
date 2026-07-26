from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.job import JobRead


AnnotationExportFormat = Literal[
    "labelme",
    "coco_detection",
    "coco_segmentation",
    "yolo_detection",
    "yolo_segmentation",
    "voc",
]

AnnotationExportIssueSeverity = Literal["error", "warning", "info"]


class AnnotationExportSampleQuery(BaseModel):
    search: str | None = None
    file_type: str | None = None
    file_status: str | None = None
    tag: str | None = None
    split: str | None = None
    review_status: str | None = None
    sample_ids: list[int] | None = None
    sort_by: str = "relative_path"
    sort_order: Literal["asc", "desc"] = "asc"


class AnnotationExportPrecheckRequest(BaseModel):
    format: AnnotationExportFormat
    sample_query: AnnotationExportSampleQuery = Field(default_factory=AnnotationExportSampleQuery)
    include_empty: bool = False


class AnnotationClassMapItem(BaseModel):
    name: str
    id: int
    coco_id: int
    yolo_id: int


class AnnotationExportIssue(BaseModel):
    severity: AnnotationExportIssueSeverity
    code: str
    message: str
    sample_id: int | None = None
    sample_path: str | None = None
    annotation_id: int | None = None


class AnnotationExportPrecheckResponse(BaseModel):
    dataset_id: int
    format: AnnotationExportFormat
    sample_count: int
    annotated_sample_count: int
    exportable_object_count: int
    skipped_object_count: int
    class_map: list[AnnotationClassMapItem] = Field(default_factory=list)
    issues: list[AnnotationExportIssue] = Field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    truncated_issue_count: int = 0
    blocked: bool


class AnnotationExportJobCreateRequest(BaseModel):
    format: Literal["labelme"] = "labelme"
    sample_query: AnnotationExportSampleQuery = Field(default_factory=AnnotationExportSampleQuery)
    include_empty: bool = False


class AnnotationExportJobParameters(AnnotationExportJobCreateRequest):
    class_map: list[AnnotationClassMapItem] = Field(default_factory=list)
    precheck_summary: dict[str, int] = Field(default_factory=dict)
    request_fingerprint: str


class AnnotationExportJobCreateResponse(BaseModel):
    job: JobRead
    created: bool
