"""Optional, local SAM inference. Predictions never write annotations or source files."""

from __future__ import annotations

import importlib.util
import logging
import os
import pickle
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import TYPE_CHECKING

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlmodel import Session

from app.core.config import get_settings
from app.schemas.sam import SamPredictRequest, SamPrediction, SamStatus
from app.services import sample_service

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray
    from segment_anything import SamPredictor

logger = logging.getLogger(__name__)
CHECKPOINT_NAME = "sam_vit_b_01ec64.pth"
MAX_IMAGE_PIXELS = 40_000_000


def checkpoint_path() -> Path:
    configured = os.getenv("SAM_CHECKPOINT")
    if configured:
        return Path(configured).expanduser().resolve()
    return get_settings().storage_root / "models" / "sam" / CHECKPOINT_NAME


def mask_to_polygons(mask: NDArray[np.bool_]) -> tuple[list[list[float]], list[str]]:
    """Keep disconnected components; disclose holes unsupported by polygon storage."""
    import cv2
    import numpy as np

    contours, hierarchy = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return [], []
    warnings: list[str] = []
    if any(item[3] >= 0 for item in hierarchy[0]):
        warnings.append("当前多边形标注不支持内部孔洞，轮廓会填充孔洞；请检查后再确认。")
    outer = [contour for contour, info in zip(contours, hierarchy[0]) if info[3] < 0]
    outer.sort(key=cv2.contourArea, reverse=True)
    polygons: list[list[float]] = []
    dropped = 0
    for contour in outer:
        if cv2.contourArea(contour) < 3:
            dropped += 1
            continue
        # Start at subpixel tolerance, then bound vertex count for editable SVGs.
        epsilon = 0.75
        polygon = cv2.approxPolyDP(contour, epsilon, True)
        while len(polygon) > 256:
            epsilon *= 1.5
            polygon = cv2.approxPolyDP(contour, epsilon, True)
        if len(polygon) < 3 or cv2.contourArea(polygon) < 1:
            dropped += 1
            continue
        polygons.append(polygon.reshape(-1).astype(float).tolist())
    if dropped:
        warnings.append(f"已忽略 {dropped} 个不足以形成有效多边形的微小区域。")
    if len(polygons) > 32:
        raise HTTPException(422, "分割区域过于零碎，请缩小目标框或增加排除点。")
    return polygons, warnings


class SamService:
    def __init__(self) -> None:
        self._lock = Lock()
        self._predictor: SamPredictor | None = None
        self._model_key: tuple[str, int, int, str] | None = None
        self._image_key: tuple[int, str, int, int] | None = None
        self._device: str | None = None

    def status(self) -> SamStatus:
        missing = [name for name in ("torch", "torchvision", "segment_anything", "cv2", "numpy")
                   if importlib.util.find_spec(name) is None]
        if missing:
            return SamStatus(ready=False, message="尚未安装 SAM 推理组件，请按 docs/sam-assisted-annotation.md 完成安装。")
        if not checkpoint_path().is_file():
            return SamStatus(ready=False, message="未找到 SAM ViT-B 权重，请运行模型下载脚本或设置 SAM_CHECKPOINT。")
        return SamStatus(ready=True, loaded=self._predictor is not None, device=self._device,
                         message="SAM ViT-B 已就绪，首次生成需要加载模型并分析图片。")

    def _load_predictor(self) -> SamPredictor:
        import torch
        from segment_anything import SamPredictor, sam_model_registry

        path = checkpoint_path()
        device = os.getenv("SAM_DEVICE", "auto").lower()
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device not in {"cpu", "cuda"}:
            raise HTTPException(503, "SAM_DEVICE 仅支持 auto、cpu 或 cuda。")
        if device == "cuda" and not torch.cuda.is_available():
            raise HTTPException(503, "CUDA 不可用，请安装匹配的 PyTorch 或将 SAM_DEVICE 设置为 cpu。")
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns, device)
        if self._predictor is None or key != self._model_key:
            self._predictor = None
            self._image_key = None
            # Limit CPU oversubscription; image features are reused for subsequent prompts.
            if device == "cpu":
                torch.set_num_threads(min(8, os.cpu_count() or 1))
            model = sam_model_registry["vit_b"](checkpoint=str(path))
            model.to(device=device)
            model.eval()
            self._predictor = SamPredictor(model)
            self._device = device
            self._model_key = key
        return self._predictor

    def predict(self, sample_id: int, path: Path, payload: SamPredictRequest) -> SamPrediction:
        availability = self.status()
        if not availability.ready:
            raise HTTPException(503, availability.message)
        if not self._lock.acquire(blocking=False):
            raise HTTPException(409, "SAM 正在处理上一请求，请稍候重试。")
        started = perf_counter()
        try:
            import numpy as np
            import torch

            before = path.stat()
            image_key = (sample_id, str(path.resolve()), before.st_size, before.st_mtime_ns)
            with Image.open(path) as image:
                width, height = image.size
                if width * height > MAX_IMAGE_PIXELS:
                    raise HTTPException(413, "图片超过 4000 万像素，请使用较小图片进行辅助分割。")
                if (width, height) != (payload.image_width, payload.image_height):
                    raise HTTPException(409, "图片尺寸已变化，请重新加载图片后再生成。")
                predictor = self._load_predictor()
                with torch.inference_mode():
                    if self._image_key != image_key:
                        self._image_key = None
                        predictor.set_image(np.asarray(image.convert("RGB")))
                        self._image_key = image_key
                    masks, scores, _ = predictor.predict(
                        point_coords=np.array([[p.x, p.y] for p in payload.points], dtype=np.float32) if payload.points else None,
                        point_labels=np.array([p.label for p in payload.points], dtype=np.int32) if payload.points else None,
                        box=np.array(payload.box, dtype=np.float32) if payload.box is not None else None,
                        multimask_output=payload.box is None and len(payload.points) == 1,
                    )
            best = int(np.argmax(scores))
            polygons, warnings = mask_to_polygons(masks[best])
            if not polygons:
                raise HTTPException(422, "未找到有效轮廓，请调整目标框或增加包含点。")
            after = path.stat()
            if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
                self._image_key = None
                raise HTTPException(409, "图片在推理期间发生变化，请重新加载后重试。")
            return SamPrediction(sample_id=sample_id, polygons=polygons, score=float(scores[best]),
                                 image_width=width, image_height=height,
                                 elapsed_ms=round((perf_counter() - started) * 1000),
                                 device=self._device or "cpu", warnings=warnings)
        except HTTPException:
            raise
        except (FileNotFoundError, PermissionError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
            self._image_key = None
            raise HTTPException(400, "无法读取模型或图片，请检查文件是否存在、可访问且格式有效。") from exc
        except (ImportError, OSError, RuntimeError, ValueError, EOFError, KeyError, pickle.UnpicklingError) as exc:
            self._image_key = None
            logger.exception("SAM inference failed for sample %s", sample_id)
            raise HTTPException(503, "SAM 运行失败，请检查推理组件、模型完整性及可用内存；详情见后端日志。") from exc
        finally:
            self._lock.release()


sam_service = SamService()


def predict_sample(session: Session, sample_id: int, payload: SamPredictRequest) -> SamPrediction:
    sample = sample_service.get_sample_or_404(session, sample_id)
    if sample.file_type != "image" or sample.file_status != "normal":
        raise HTTPException(400, "SAM 仅支持正常状态的图片样本。")
    path = Path(sample.absolute_path)
    if not path.is_file():
        raise HTTPException(404, "图片文件不存在。")
    return sam_service.predict(sample_id, path, payload)
