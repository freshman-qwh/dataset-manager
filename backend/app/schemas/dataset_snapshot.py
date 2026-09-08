from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.annotation_export import AnnotationClassMapItem, AnnotationExportSampleQuery
from app.schemas.training_readiness import TrainingReadinessExportFormat


class DatasetSnapshotExportConfig(BaseModel):
    format: TrainingReadinessExportFormat = "manifest"
    include_empty: bool = False
    class_map: list[AnnotationClassMapItem] = Field(default_factory=list)


class DatasetSnapshotCreate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    sample_query: AnnotationExportSampleQuery = Field(default_factory=AnnotationExportSampleQuery)
    export_config: DatasetSnapshotExportConfig = Field(default_factory=DatasetSnapshotExportConfig)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        normalized = value.strip() if value else ""
        return normalized or None

    @field_validator("sample_query")
    @classmethod
    def normalize_sample_ids(cls, value: AnnotationExportSampleQuery) -> AnnotationExportSampleQuery:
        if value.sample_ids is not None:
            value.sample_ids = sorted(set(value.sample_ids))
        return value


class DatasetSnapshotRead(BaseModel):
    id: int
    dataset_id: int
    dataset_revision: int
    name: str | None = None
    content_sha256: str
    sample_count: int
    annotation_count: int
    class_count: int
    sample_query: AnnotationExportSampleQuery
    export_config: DatasetSnapshotExportConfig
    created_at: datetime


class DatasetSnapshotContent(BaseModel):
    schema_version: Literal[1]
    dataset: dict[str, object]
    sample_query: AnnotationExportSampleQuery
    export_config: DatasetSnapshotExportConfig
    class_map: list[AnnotationClassMapItem]
    tag_catalog: list[dict[str, object]]
    annotation_class_catalog: list[dict[str, object]]
    sample_count: int
    annotation_count: int
    samples: list[dict[str, object]]


class DatasetSnapshotDocument(BaseModel):
    snapshot_id: int
    dataset_id: int
    dataset_revision: int
    created_at: datetime
    content_sha256: str
    content: DatasetSnapshotContent


DatasetSnapshotChangeType = Literal[
    "added",
    "removed",
    "file",
    "metadata",
    "tags",
    "split",
    "annotations",
]


class DatasetSnapshotDiffSummary(BaseModel):
    added: int = 0
    removed: int = 0
    file_changed: int = 0
    metadata_changed: int = 0
    tags_changed: int = 0
    split_changed: int = 0
    annotations_changed: int = 0
    changed_samples: int = 0


class DatasetSnapshotDiffItem(BaseModel):
    sample_id: int
    relative_path: str
    change_types: list[DatasetSnapshotChangeType]
    before: dict[str, object] | None = None
    after: dict[str, object] | None = None


class DatasetSnapshotDiffResponse(BaseModel):
    dataset_id: int
    base_snapshot_id: int
    target_snapshot_id: int
    base_revision: int
    target_revision: int
    summary: DatasetSnapshotDiffSummary
    total: int
    page: int
    page_size: int
    items: list[DatasetSnapshotDiffItem]


class DatasetSnapshotTrainingLabels(BaseModel):
    schema_version: Literal[1]
    snapshot_id: int
    dataset_id: int
    dataset_revision: int
    snapshot_content_sha256: str
    format: TrainingReadinessExportFormat
    include_empty: bool
    class_map: list[AnnotationClassMapItem]
    sample_count: int
    label_sha256: str
    labels: list[dict[str, object]]
