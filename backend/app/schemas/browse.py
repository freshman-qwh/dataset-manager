from pydantic import BaseModel

from app.schemas.sample import SampleRead


class BrowseFolder(BaseModel):
    name: str
    path: str
    sample_count: int
    image_count: int
    cover_sample_id: int | None = None
    cover_file_hash: str | None = None


class BrowseSource(BaseModel):
    path: str
    sample_count: int
    image_count: int


class DatasetBrowseResponse(BaseModel):
    dataset_id: int
    folder: str
    recursive: bool
    source_root: str
    sources: list[BrowseSource]
    folders: list[BrowseFolder]
    folders_total: int
    folder_page: int
    folder_page_size: int
    items: list[SampleRead]
    total: int
    page: int
    page_size: int
