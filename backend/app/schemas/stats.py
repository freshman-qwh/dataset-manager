from pydantic import BaseModel


class DatasetStats(BaseModel):
    dataset_id: int
    sample_count: int
    total_size: int
    by_file_type: dict[str, int]
    by_extension: dict[str, int]
    tag_counts: dict[str, int]
