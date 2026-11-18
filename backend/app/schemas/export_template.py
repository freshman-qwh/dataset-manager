from typing import Literal

from pydantic import BaseModel, Field


MetadataExportScope = Literal["filtered", "all"]


class ExportTemplateResponse(BaseModel):
    dataset_id: int
    format: str
    description: str
    scope: MetadataExportScope
    sample_count: int
    payload: dict[str, object] = Field(default_factory=dict)
