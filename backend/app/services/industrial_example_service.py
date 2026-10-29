"""Generate an explicitly requested synthetic example in application storage."""
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw
from sqlmodel import Session, select

from app.core.config import get_settings
from app.models.dataset import Dataset
from app.models.sample import Sample
from app.schemas.dataset import DatasetCreate
from app.schemas.scan import ScanRequest
from app.services import dataset_service, scan_service
from app.services.dataset_revision_service import bump_dataset_revision


def create_example(session: Session):
    previous = session.exec(select(Dataset).where(Dataset.source == "builtin-industrial-demo")).first()
    if previous:
        return dataset_service.get_dataset(session, previous.id)
    root = get_settings().storage_root / "datasets" / f"industrial-example-{uuid4().hex}"
    root.mkdir(parents=True)
    for i in range(16):
        image = Image.new("RGB", (320, 240), (225, 228, 230))
        draw = ImageDraw.Draw(image)
        draw.rectangle((60, 45, 260, 195), fill=(160 + i, 170, 180), outline=(60, 70, 80), width=3)
        draw.text((10, 10), f"Synthetic part {i // 2 + 1}, view {i % 2 + 1}", fill="black")
        if i >= 10:
            draw.line((100, 85, 200, 155), fill=(180, 30, 30), width=5)
        image.save(root / f"part_{i // 2 + 1:02d}_view_{i % 2 + 1}.png")
    dataset = dataset_service.create_dataset(session, DatasetCreate(
        name="工业异常检测示例（合成图片）", workflow_profile="industrial_anomaly",
        root_path=str(root), source="builtin-industrial-demo",
        description="仅用于熟悉分拣、分组和导出流程，不用于证明算法效果。可删除项目记录，原始文件仍保留。",
    ))
    scan_service.scan_dataset(session, dataset.id, ScanRequest(folder_path=str(root)))
    samples = session.exec(select(Sample).where(Sample.dataset_id == dataset.id).order_by(Sample.filename)).all()
    for i, sample in enumerate(samples):
        sample.capture_group_id = sample.filename.rsplit("_view_", 1)[0]
        sample.capture_batch_id = "synthetic-batch-1"
        sample.triage_status = "ok" if i < 10 else "ng"
        sample.ok_grade = "clear" if i < 10 else None
        sample.triage_version = 1
        sample.triage_policy_version = 1
        sample.triaged_file_hash = sample.file_hash
        session.add(sample)
    bump_dataset_revision(session, dataset.id)
    session.commit()
    return dataset_service.get_dataset(session, dataset.id)
