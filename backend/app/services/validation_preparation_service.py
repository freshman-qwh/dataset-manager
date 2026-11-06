"""Small image preparation tools. All image access is read-only."""
import json
from datetime import timezone
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, ImageFilter, ImageOps, ImageStat
from sqlalchemy import text
from sqlmodel import Session, select
from app.models.sample import Sample
from app.services import sample_service
from app.services.dataset_revision_service import bump_dataset_revision
from app.services.dataset_service import get_dataset_or_404
from app.schemas.validation import NormalizedRoi


def settings(session: Session, dataset_id: int) -> dict:
    dataset = get_dataset_or_404(session, dataset_id)
    roi = json.loads(dataset.industrial_settings_json or "{}").get("validation_roi")
    references = session.exec(select(Sample).where(Sample.dataset_id == dataset_id,
        Sample.file_type == "image", Sample.file_status == "normal").order_by((Sample.triage_status == "ok").desc(), Sample.relative_path).limit(20)).all()
    return dict(roi=roi, dataset_revision=dataset.revision,
        references=[dict(sample_id=s.id,relative_path=s.relative_path) for s in references])


def save_roi(session: Session, dataset_id: int, payload) -> dict:
    session.commit(); session.exec(text("BEGIN IMMEDIATE"))
    try:
        dataset = get_dataset_or_404(session, dataset_id)
        if dataset.revision != payload.expected_dataset_revision:
            raise HTTPException(409, "项目已变化，请刷新区域设置后再保存。")
        values = json.loads(dataset.industrial_settings_json or "{}")
        roi = payload.roi.model_dump() if payload.roi else None
        if values.get("validation_roi") != roi:
            values["validation_roi"] = roi
            dataset.industrial_settings_json = json.dumps(values)
            session.add(dataset); bump_dataset_revision(session,dataset_id)
        session.commit()
        return settings(session,dataset_id)
    except Exception:
        session.rollback(); raise


def crop_box(size, roi: NormalizedRoi | None):
    w,h = size
    if roi is None:
        return 0,0,w,h
    box = round(roi.x*w),round(roi.y*h),round((roi.x+roi.width)*w),round((roi.y+roi.height)*h)
    if box[2]-box[0] < 4 or box[3]-box[1] < 4:
        raise ValueError("ROI 小于 4 像素，请扩大区域。")
    return box


def inspect_quality(session: Session, dataset_id: int, request) -> dict:
    dataset = get_dataset_or_404(session,dataset_id)
    revision = dataset.revision
    query = request.sample_query.model_dump(exclude={"expected_dataset_revision","completed_only"})
    samples = sample_service.get_filtered_samples(session,dataset_id,**query)
    if request.sample_query.sample_ids and set(request.sample_query.sample_ids)-{s.id for s in samples}:
        raise HTTPException(422,"所选图片不属于当前范围。")
    if not samples or len(samples)>300:
        raise HTTPException(422,"只读体检每次支持 1–300 张图片，请在数据页筛选或选择后带入范围。")
    images, fingerprints = [], {}
    for sample in samples:
        row = dict(sample_id=sample.id,relative_path=sample.relative_path,sha256=sample.file_hash,
            brightness=None,sharpness=None,issues=[],error=None)
        try:
            path = Path(sample.absolute_path)
            before = path.stat()
            modified_at = sample.file_modified_at
            if modified_at is not None and modified_at.tzinfo is None:
                modified_at = modified_at.replace(tzinfo=timezone.utc)
            if (sample.file_type != "image" or sample.file_status != "normal"
                    or before.st_size != sample.file_size
                    or modified_at is not None and abs(before.st_mtime - modified_at.timestamp()) > 0.00001):
                raise ValueError("不是可用图片或内容已变化，请重新扫描。")
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert("L")
            image = image.crop(crop_box(image.size,request.roi))
            image = image.resize((128,128),Image.Resampling.BILINEAR)
            brightness = ImageStat.Stat(image).mean[0]
            sharpness = ImageStat.Stat(image.filter(ImageFilter.FIND_EDGES).crop((1,1,127,127))).var[0]
            row.update(brightness=round(brightness,2),sharpness=round(sharpness,2))
            if brightness < request.dark_below: row["issues"].append("偏暗候选")
            if brightness > request.bright_above: row["issues"].append("偏亮候选")
            if sharpness < request.sharpness_below: row["issues"].append("低纹理或可能模糊")
            tiny = image.resize((9,8),Image.Resampling.BILINEAR)
            pixels = [tiny.getpixel((x,y)) for y in range(8) for x in range(9)]
            fingerprint = 0
            for y in range(8):
                for x in range(8):
                    fingerprint = (fingerprint << 1) | int(pixels[y*9+x] > pixels[y*9+x+1])
            # Measurements decode the image once; use cheap metadata to catch
            # concurrent edits instead of rereading its contents for checksums.
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise ValueError("体检过程中内容变化，请重新扫描。")
            fingerprints[sample.id] = fingerprint
        except (OSError,ValueError,Image.DecompressionBombError) as exc:
            row.update(error=str(exc),brightness=None,sharpness=None,issues=["文件需检查"])
        images.append(row)
    pairs = []
    for i,left in enumerate(images):
        if left["sample_id"] not in fingerprints: continue
        for right in images[i+1:]:
            if right["sample_id"] not in fingerprints: continue
            distance = (fingerprints[left["sample_id"]] ^ fingerprints[right["sample_id"]]).bit_count()
            exact = left["sha256"] == right["sha256"]
            if exact or distance <= request.similar_distance:
                pairs.append(dict(left_id=left["sample_id"],right_id=right["sample_id"],distance=distance,exact_duplicate=exact))
    pairs.sort(key=lambda p:(not p["exact_duplicate"],p["distance"],p["left_id"],p["right_id"]))
    session.expire_all()
    if get_dataset_or_404(session,dataset_id).revision != revision:
        raise HTTPException(409,"体检过程中项目已变化，请重新检查。")
    return dict(dataset_revision=revision,parameters=request.model_dump(mode="json"),images=images,
        processed=sum(row["error"] is None for row in images),failed=sum(row["error"] is not None for row in images),
        pairs=pairs[:200],pair_count=len(pairs),pairs_truncated=len(pairs)>200,
        notice="只读候选检查：亮度为灰度均值，清晰度为统一缩放后的边缘方差；低纹理不等于失焦。近重复为 64 位差异哈希候选，不证明同工件。请按产品与相机核对，不自动删图、合组或修改判定。")
