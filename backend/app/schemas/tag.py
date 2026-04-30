from pydantic import BaseModel, ConfigDict, Field


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=1000)
    parent_id: int | None = None
    aliases: list[str] = Field(default_factory=list)


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=1000)
    parent_id: int | None = None
    aliases: list[str] | None = None


class TagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dataset_id: int
    name: str
    color: str | None = None
    description: str | None = None
    parent_id: int | None = None
    aliases: list[str] = Field(default_factory=list)
