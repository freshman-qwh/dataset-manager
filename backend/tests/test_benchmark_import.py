from pathlib import Path
import csv

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import datasets, samples
from app.core.database import get_session
from app.models.dataset import Dataset
from app.models.organization import DatasetBatch, DatasetCategory
from app.models.sample import Sample
from app.schemas.scan import ScanRequest
from app.services import scan_service, scan_job_service
from app.services.benchmark_import_service import inspect_benchmark


def image(path: Path, size=(12, 10)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", size, 255).save(path)
    return path


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as value:
        yield value
    engine.dispose()


def dataset(session, root, name="Bench"):
    value = Dataset(name=name, root_path=str(root), workflow_profile="industrial_anomaly")
    session.add(value)
    session.commit()
    session.refresh(value)
    return value


def mvtec(root):
    image(root / "bottle/train/good/000.png")
    image(root / "bottle/test/good/001.png")
    image(root / "bottle/test/broken/002.png")
    image(root / "bottle/ground_truth/broken/002_mask.png")
    image(root / "cable/train/good/000.png")
    image(root / "cable/test/good/001.png")


def test_mvtec_import_links_masks_categories_official_truth_and_preserves_originals(session, tmp_path):
    root = tmp_path / "mvtec"
    mvtec(root)
    before = {p: p.read_bytes() for p in root.rglob("*.png")}
    value = dataset(session, root)
    preview = scan_service.preview_import(session, value.id, ScanRequest())
    assert preview.detected_format == "mvtec_ad"
    assert preview.categories == ["bottle", "cable"]
    assert preview.image_count == 5 and preview.mask_count == 1
    assert preview.official_split_counts == {"train": 2, "test": 3}
    assert not session.exec(select(DatasetCategory)).all()
    result = scan_service.scan_dataset(session, value.id, ScanRequest(new_batch_name="First"))
    assert result.imported == 5 and result.linked_masks == 1
    items = session.exec(select(Sample)).all()
    assert len(items) == 5 and all("ground_truth" not in row.relative_path for row in items)
    abnormal = next(row for row in items if row.benchmark_label == "anomaly")
    assert abnormal.triage_status == "ng" and abnormal.split == abnormal.official_split == "test"
    assert abnormal.triaged_file_hash == abnormal.file_hash
    assert abnormal.mask_path.endswith("002_mask.png")
    assert all(row.batch_id == result.assigned_batch_id for row in items)
    assert len(session.exec(select(DatasetCategory)).all()) == 2
    assert {p: p.read_bytes() for p in root.rglob("*.png")} == before


def test_rescan_does_not_rewrite_human_decisions_old_batches_or_old_mask_records(session, tmp_path):
    root = tmp_path / "mvtec"
    mvtec(root)
    value = dataset(session, root)
    scan_service.scan_dataset(session, value.id, ScanRequest(import_format="folder", new_batch_name="Legacy"))
    # Legacy ordinary scans already registered mask PNGs. They stay readable;
    # format recognition must not delete previous user records.
    initial = session.exec(select(Sample)).all()
    assert len(initial) == 6
    row = next(row for row in initial if "test/broken" in row.relative_path)
    row.triage_status = "pending"
    row.split = "val"
    row.capture_group_id = "manual-group"
    old_batch = row.batch_id
    session.add(row)
    session.commit()
    result = scan_service.scan_dataset(session, value.id, ScanRequest(import_format="mvtec_ad", new_batch_name="New"))
    session.refresh(row)
    assert result.imported == 0
    assert row.triage_status == "pending" and row.split == "val"
    assert row.capture_group_id == "manual-group" and row.batch_id == old_batch
    assert row.category_id is None and row.mask_path is None
    assert len(session.exec(select(Sample)).all()) == 6
    assert all(sample.file_status == "normal" for sample in session.exec(select(Sample)).all())


def test_import_existing_batch_only_assigns_new_files_and_rejects_foreign_batch(session, tmp_path):
    root = tmp_path / "plain"
    image(root / "one.png")
    first = dataset(session, root)
    second = dataset(session, root, "Other")
    foreign = DatasetBatch(dataset_id=second.id, name="Foreign")
    session.add(foreign); session.commit()
    with pytest.raises(HTTPException):
        scan_service.scan_dataset(session, first.id, ScanRequest(batch_id=foreign.id))
    scan_service.scan_dataset(session, first.id, ScanRequest(new_batch_name="One"))
    previous = session.exec(select(Sample).where(Sample.dataset_id == first.id)).one()
    previous.capture_group_id = "part-1"; session.add(previous); session.commit()
    image(root / "two.png")
    second_batch = DatasetBatch(dataset_id=first.id, name="Two")
    session.add(second_batch); session.commit()
    result = scan_service.scan_dataset(session, first.id, ScanRequest(batch_id=second_batch.id))
    session.refresh(previous)
    new = session.exec(select(Sample).where(Sample.dataset_id == first.id, Sample.filename == "two.png")).one()
    assert result.imported == 1
    assert new.batch_id == second_batch.id and new.capture_batch_id == second_batch.code
    assert previous.batch_id != second_batch.id and previous.capture_group_id == "part-1"


def test_visA_raw_uses_local_official_csv_and_no_invented_validation_split(session, tmp_path):
    root = tmp_path / "visa"
    image(root / "candle/Data/Images/Normal/a.png")
    image(root / "candle/Data/Images/Anomaly/b.png")
    image(root / "candle/Data/Masks/Anomaly/b.png")
    index = root / "split_csv/1cls.csv"
    index.parent.mkdir()
    index.write_text("object,split,label,image,mask\ncandle,train,normal,candle/Data/Images/Normal/a.png,\ncandle,test,anomaly,candle/Data/Images/Anomaly/b.png,candle/Data/Masks/Anomaly/b.png\n")
    value = dataset(session, root)
    result = scan_service.scan_dataset(session, value.id, ScanRequest())
    rows = session.exec(select(Sample)).all()
    assert result.detected_format == "visa" and result.imported == 2
    assert {row.official_split for row in rows} == {"train", "test"}
    assert {row.benchmark_label for row in rows} == {"normal", "anomaly"}
    assert sum(row.mask_path is not None for row in rows) == 1


def test_visa_bundled_index_is_offline_and_supports_single_category_root(tmp_path):
    root = tmp_path / "candle"
    image(root / "Data/Images/Normal/0836.JPG")
    image(root / "Data/Images/Anomaly/000.JPG")
    image(root / "Data/Masks/Anomaly/000.png")
    result = inspect_benchmark(root)
    assert result.format == "visa"
    assert {item.split for item in result.images.values()} == {"train", "test"}
    assert len(result.images) == 2 and result.preview().mask_count == 1
    assert any("随软件" in warning for warning in result.warnings)


def test_visa_prepared_layout_and_mask_filename(tmp_path):
    root = tmp_path / "visa-pytorch"
    image(root / "1cls/candle/train/good/a.png")
    image(root / "1cls/candle/test/bad/b.JPG")
    image(root / "1cls/candle/ground_truth/bad/b.png")
    result = inspect_benchmark(root)
    assert result.format == "visa" and result.preview().mask_count == 1
    assert result.preview().official_split_counts == {"train": 1, "test": 1}


@pytest.mark.parametrize("row", [
    "candle,test,anomaly,../outside.png,",
    "candle,test,anomaly,candle/Data/Images/Anomaly/b.png,../../outside.png",
    "candle,test,normal,candle/Data/Images/Anomaly/b.png,",
    "candle,validation,anomaly,candle/Data/Images/Anomaly/b.png,",
])
def test_visa_rejects_unsafe_or_contradictory_official_rows(tmp_path, row):
    root = tmp_path / "visa"
    image(root / "candle/Data/Images/Anomaly/b.png")
    index = root / "split_csv/1cls.csv"; index.parent.mkdir()
    index.write_text("object,split,label,image,mask\n" + row + "\n")
    with pytest.raises(HTTPException) as exc:
        inspect_benchmark(root)
    assert exc.value.status_code == 422


def test_mask_dimension_mismatch_warns_and_never_attaches_wrong_mask(tmp_path):
    root = tmp_path / "mvtec"
    mvtec(root)
    image(root / "bottle/ground_truth/broken/002_mask.png", (3, 4))
    result = inspect_benchmark(root)
    assert result.preview().mask_count == 0
    assert any("尺寸" in warning for warning in result.warnings)


def test_import_preview_and_linked_mask_endpoint(session, tmp_path):
    root = tmp_path / "mvtec"; mvtec(root)
    value = dataset(session, root)
    app = FastAPI(); app.include_router(datasets.router); app.include_router(samples.router)
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        response = client.post(f"/api/datasets/{value.id}/import-preview", json={"folder_path":str(root)})
        assert response.status_code == 200 and response.json()["mask_count"] == 1
        assert not session.exec(select(Sample)).all()
        scan_service.scan_dataset(session, value.id, ScanRequest())
        anomaly = session.exec(select(Sample).where(Sample.benchmark_label == "anomaly")).one()
        normal = session.exec(select(Sample).where(Sample.benchmark_label == "normal")).first()
        assert client.get(f"/api/samples/{anomaly.id}/mask").status_code == 200
        assert client.get(f"/api/samples/{normal.id}/mask").status_code == 404


def test_scan_job_freezes_created_batch_identity_for_retry(session, tmp_path):
    root = tmp_path / "plain"; image(root / "one.png")
    value = dataset(session, root)
    result = scan_job_service.create_scan_job(session, value.id, ScanRequest(new_batch_name="First", import_format="folder", recognize_existing=True))
    assert result.job.parameters["batch_id"] > 0
    assert result.job.parameters["import_format"] == "folder"
    assert result.job.parameters["recognize_existing"] is True
    assert "new_batch_name" not in result.job.parameters
    request = ScanRequest.model_validate(result.job.parameters)
    scan_service.scan_dataset(session, value.id, request)
    scan_service.scan_dataset(session, value.id, request)
    assert len(session.exec(select(DatasetBatch)).all()) == 1
    assert len(session.exec(select(Sample)).all()) == 1


def test_explicit_recognition_fills_only_empty_semantics_preserves_human_fields_and_is_idempotent(session, tmp_path):
    root = tmp_path / "mvtec"
    mvtec(root)
    value = dataset(session, root)
    scan_service.scan_dataset(session, value.id, ScanRequest(import_format="folder", new_batch_name="Original"))
    rows = session.exec(select(Sample)).all()
    anomaly = next(row for row in rows if row.relative_path == "bottle/test/broken/002.png")
    normal = next(row for row in rows if row.relative_path == "bottle/train/good/000.png")
    category = DatasetCategory(dataset_id=value.id, name="Manually assigned")
    session.add(category); session.flush()
    normal.category_id = category.id
    normal.import_format = "custom"
    normal.official_split = "val"
    anomaly.triage_status = "pending"
    anomaly.split = "val"
    anomaly.capture_group_id = "manual-part"
    anomaly.triage_version = 7
    for row in [anomaly, normal]:
        session.add(row)
    session.commit()
    identity = (anomaly.id, anomaly.file_hash, anomaly.batch_id, anomaly.capture_batch_id, anomaly.capture_group_id,
        anomaly.triage_status, anomaly.split, anomaly.triage_version, anomaly.triaged_file_hash)
    session.refresh(value)
    before_revision = value.revision
    request = ScanRequest(import_format="mvtec_ad", recognize_existing=True)
    preview = scan_service.preview_import(session, value.id, request)
    assert any("仅补充空" in warning for warning in preview.warnings)
    assert anomaly.category_id is None and anomaly.mask_path is None  # Preview stays read-only.
    result = scan_service.scan_dataset(session, value.id, request)
    session.refresh(anomaly); session.refresh(normal); session.refresh(value)
    assert result.imported == 0 and result.updated == 5
    assert anomaly.category_id is not None and anomaly.mask_path.endswith("002_mask.png")
    assert anomaly.official_split == "test" and anomaly.benchmark_label == "anomaly"
    assert identity == (anomaly.id, anomaly.file_hash, anomaly.batch_id, anomaly.capture_batch_id, anomaly.capture_group_id,
        anomaly.triage_status, anomaly.split, anomaly.triage_version, anomaly.triaged_file_hash)
    assert normal.category_id == category.id and normal.import_format == "custom" and normal.official_split == "val"
    assert value.revision == before_revision + 1
    revision = value.revision
    repeated = scan_service.scan_dataset(session, value.id, request)
    session.refresh(value)
    assert repeated.updated == 0 and repeated.unchanged == 5
    assert value.revision == revision
    assert len(session.exec(select(Sample)).all()) == 6
    mask_record = next(row for row in session.exec(select(Sample)).all() if "ground_truth" in row.relative_path)
    assert mask_record.category_id is None and mask_record.file_status == "normal"
