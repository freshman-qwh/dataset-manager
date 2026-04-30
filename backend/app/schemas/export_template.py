from pydantic import BaseModel, Field


class ExportTemplateResponse(BaseModel):
    dataset_id: int
    format: str
    description: str
    payload: dict[str, object] = Field(default_factory=dict)
