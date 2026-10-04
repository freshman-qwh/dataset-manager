from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SamPoint(BaseModel):
    x: float = Field(ge=0, allow_inf_nan=False)
    y: float = Field(ge=0, allow_inf_nan=False)
    label: Literal[0, 1] = 1


class SamPredictRequest(BaseModel):
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    points: list[SamPoint] = Field(default_factory=list, max_length=64)
    box: list[float] | None = Field(default=None, min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_prompts(self) -> "SamPredictRequest":
        import math

        if not self.box and not any(point.label == 1 for point in self.points):
            raise ValueError("请先添加一个包含点或目标框。")
        if any(point.x >= self.image_width or point.y >= self.image_height for point in self.points):
            raise ValueError("提示点必须位于图片内。")
        if self.box is not None:
            x1, y1, x2, y2 = self.box
            if not all(math.isfinite(value) for value in self.box):
                raise ValueError("框坐标必须为有限数值。")
            if not (0 <= x1 < x2 <= self.image_width and 0 <= y1 < y2 <= self.image_height):
                raise ValueError("目标框必须位于图片内且具有正面积。")
        return self


class SamStatus(BaseModel):
    ready: bool
    model: Literal["sam_vit_b"] = "sam_vit_b"
    loaded: bool = False
    device: str | None = None
    message: str


class SamPrediction(BaseModel):
    sample_id: int
    model: Literal["sam_vit_b"] = "sam_vit_b"
    polygons: list[list[float]]
    score: float
    image_width: int
    image_height: int
    elapsed_ms: int
    device: str
    warnings: list[str] = Field(default_factory=list)
