from pydantic import BaseModel, Field


class DatasetStats(BaseModel):
    dataset_id: int
    sample_count: int
    total_size: int
    by_file_type: dict[str, int]
    by_extension: dict[str, int]
    by_status: dict[str, int]
    by_split: dict[str, int]
    by_annotation_progress: dict[str, int]
    by_review_status: dict[str, int]
    tag_counts: dict[str, int]
    duplicate_groups: int = 0
    duplicate_samples: int = 0
    untagged_samples: int = 0
    samples_with_objects: int = 0
    annotation_count: int = 0
    by_annotation_label: dict[str, int] = Field(default_factory=dict)
