import hashlib
import pickle
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.main import app
from app.models.dataset import Dataset
from app.models.sample import Sample
from app.schemas.sam import SamPrediction, SamStatus
from app.services import sam_service as module


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    image_path = tmp_path / "原图 sample.png"
    Image.new("RGB", (80, 60), "white").save(image_path)
    with Session(engine) as session:
        dataset = Dataset(name="SAM test", task_type="segmentation", root_path=str(tmp_path))
        session.add(dataset)
        session.flush()
        sample = Sample(dataset_id=dataset.id, filename=image_path.name, absolute_path=str(image_path),
                        relative_path=image_path.name, file_type="image", extension=".png", file_hash="original")
        session.add(sample)
        session.commit()
        sample_id = sample.id

    def session_override():
        with Session(engine) as session:
            yield session

    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = session_override
    service = module.SamService()
    monkeypatch.setattr(module, "sam_service", service)
    monkeypatch.setattr("app.api.sam.sam_service", service)
    monkeypatch.setattr(module, "checkpoint_path", lambda: tmp_path / "model.pth")
    client = TestClient(app)
    yield SimpleNamespace(client=client, service=service, sample_id=sample_id, path=image_path, engine=engine)
    client.close()
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original_overrides)
    engine.dispose()


def prompts(**changes):
    return {"image_width": 80, "image_height": 60,
            "points": [{"x": 25, "y": 25, "label": 1}], **changes}


@pytest.mark.parametrize("change", [
    {"points": []}, {"points": [{"x": 2, "y": 3, "label": 0}]},
    {"points": [{"x": -1, "y": 3, "label": 1}]},
    {"points": [{"x": 80, "y": 3, "label": 1}]},
    {"points": [{"x": 1, "y": 60, "label": 1}]},
    {"points": [{"x": 1, "y": 3, "label": 2}]},
    {"points": [{"x": 1, "y": 3, "label": 1}] * 65},
    {"box": [20, 20, 1, 1]}, {"box": [0, 0, 90, 50]}, {"box": [1, 1, 1, 20]},
    {"box": [0, 0, 10]}, {"image_width": 0}, {"box": [0, 0, "NaN", 2]},
    {"points": [{"x": "NaN", "y": 3, "label": 1}]},
])
def test_invalid_prompts_are_rejected(workspace, change):
    response = workspace.client.post(f"/api/samples/{workspace.sample_id}/sam/predict", json=prompts(**change))
    assert response.status_code == 422


def test_missing_runtime_is_reported_without_importing_torch(workspace, monkeypatch):
    monkeypatch.setattr(module.importlib.util, "find_spec", lambda name: None)
    assert workspace.client.get("/api/sam/status").json()["ready"] is False
    response = workspace.client.post(f"/api/samples/{workspace.sample_id}/sam/predict", json=prompts())
    assert response.status_code == 503
    assert "推理组件" in response.json()["detail"]


def test_missing_checkpoint_and_sample_are_explicit(workspace, monkeypatch):
    monkeypatch.setattr(module.importlib.util, "find_spec", lambda name: object())
    response = workspace.client.get("/api/sam/status")
    assert response.status_code == 200 and not response.json()["ready"]
    assert "权重" in response.json()["message"]
    assert workspace.client.post("/api/samples/9999/sam/predict", json=prompts()).status_code == 404
    workspace.path.unlink()
    assert workspace.client.post(f"/api/samples/{workspace.sample_id}/sam/predict", json=prompts()).status_code == 404


def test_invalid_sample_type_is_rejected(workspace):
    with Session(workspace.engine) as session:
        sample = session.get(Sample, workspace.sample_id)
        sample.file_type = "video"
        session.add(sample)
        session.commit()
    assert workspace.client.post(f"/api/samples/{workspace.sample_id}/sam/predict", json=prompts()).status_code == 400


def test_preview_is_read_only_then_polygon_can_be_manually_saved(workspace, monkeypatch):
    expected = [10., 10., 45., 10., 45., 40., 10., 40.]
    def predict(sample_id, path, payload):
        return SamPrediction(sample_id=sample_id, polygons=[expected], score=.9,
                             image_width=80, image_height=60, elapsed_ms=1, device="cpu")
    monkeypatch.setattr(workspace.service, "predict", predict)
    before_hash = hashlib.sha256(workspace.path.read_bytes()).hexdigest()
    before = workspace.client.get(f"/api/samples/{workspace.sample_id}").json()
    response = workspace.client.post(f"/api/samples/{workspace.sample_id}/sam/predict", json=prompts())
    assert response.status_code == 200 and response.json()["polygons"] == [expected]
    assert workspace.client.get(f"/api/samples/{workspace.sample_id}/annotations").json() == []
    after = workspace.client.get(f"/api/samples/{workspace.sample_id}").json()
    for field in ("annotation_progress", "review_status", "updated_at"):
        assert after[field] == before[field]
    expected[0] = 12.  # The user adjusts a vertex before explicitly saving.
    saved = workspace.client.put(f"/api/samples/{workspace.sample_id}/annotations", json={
        "annotations": [{"label": "target", "shape_type": "polygon", "points": expected, "source": "sam_vit_b"}],
        "save_mode": "complete",
    })
    assert saved.status_code == 200 and saved.json()[0]["points"] == expected
    assert saved.json()[0]["source"] == "sam_vit_b"
    assert hashlib.sha256(workspace.path.read_bytes()).hexdigest() == before_hash


@pytest.fixture
def fake_predictor(workspace, monkeypatch):
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    pytest.importorskip("torch")
    class Predictor:
        calls = 0
        last = None
        def set_image(self, image):
            self.calls += 1
            assert image.shape == (60, 80, 3)
        def predict(self, **kwargs):
            self.last = kwargs
            mask = np.zeros((1, 60, 80), dtype=bool)
            mask[0, 10:41, 10:46] = True
            return mask, np.array([.95]), None
    predictor = Predictor()
    monkeypatch.setattr(workspace.service, "status", lambda: SamStatus(ready=True, message="ready"))
    monkeypatch.setattr(workspace.service, "_load_predictor", lambda: predictor)
    return predictor


def test_embedding_reused_and_positive_negative_box_passed(workspace, fake_predictor):
    endpoint = f"/api/samples/{workspace.sample_id}/sam/predict"
    assert workspace.client.post(endpoint, json=prompts()).status_code == 200
    payload = prompts(box=[5, 5, 50, 45], points=[{"x": 25, "y": 25, "label": 1}, {"x": 3, "y": 3, "label": 0}])
    assert workspace.client.post(endpoint, json=payload).status_code == 200
    assert fake_predictor.calls == 1
    assert fake_predictor.last["point_labels"].tolist() == [1, 0]
    assert fake_predictor.last["box"].tolist() == [5, 5, 50, 45]
    assert fake_predictor.last["multimask_output"] is False
    Image.new("RGB", (80, 60), "blue").save(workspace.path)
    assert workspace.client.post(endpoint, json=prompts()).status_code == 200
    assert fake_predictor.calls == 2


def test_stale_dimensions_busy_and_image_limit(workspace, fake_predictor, monkeypatch):
    endpoint = f"/api/samples/{workspace.sample_id}/sam/predict"
    assert workspace.client.post(endpoint, json=prompts(image_width=81)).status_code == 409
    workspace.service._lock.acquire()
    try:
        assert workspace.client.post(endpoint, json=prompts()).status_code == 409
    finally:
        workspace.service._lock.release()
    monkeypatch.setattr(module, "MAX_IMAGE_PIXELS", 100)
    assert workspace.client.post(endpoint, json=prompts()).status_code == 413


@pytest.mark.parametrize("failure", [RuntimeError("out of memory"), pickle.UnpicklingError("invalid checkpoint"), KeyError("missing weight")])
def test_runtime_failure_releases_lock_and_invalidates_cache(workspace, fake_predictor, monkeypatch, failure):
    def fail(**kwargs):
        raise failure
    monkeypatch.setattr(fake_predictor, "predict", fail)
    response = workspace.client.post(f"/api/samples/{workspace.sample_id}/sam/predict", json=prompts())
    assert response.status_code == 503
    assert workspace.service._image_key is None
    assert not workspace.service._lock.locked()


def test_contours_keep_components_and_disclose_holes():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    mask = np.zeros((100, 100), dtype=bool)
    mask[10:50, 10:50] = True
    mask[20:30, 20:30] = False
    mask[60:90, 60:90] = True
    polygons, warnings = module.mask_to_polygons(mask)
    assert len(polygons) == 2 and all(len(points) >= 6 for points in polygons)
    assert any("孔洞" in warning for warning in warnings)
    assert module.mask_to_polygons(np.zeros((20, 20), dtype=bool)) == ([], [])


def test_tiny_contour_and_excess_components():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from fastapi import HTTPException
    mask = np.zeros((100, 100), dtype=bool)
    mask[1, 1] = True
    polygons, warnings = module.mask_to_polygons(mask)
    assert not polygons and warnings
    for y in range(0, 90, 10):
        for x in range(0, 90, 10):
            mask[y:y+5, x:x+5] = True
    with pytest.raises(HTTPException) as error:
        module.mask_to_polygons(mask)
    assert error.value.status_code == 422


def test_image_change_during_inference_is_rejected(workspace, fake_predictor, monkeypatch):
    original_predict = fake_predictor.predict
    def predict_and_change(**kwargs):
        result = original_predict(**kwargs)
        Image.new("RGB", (80, 60), "green").save(workspace.path)
        return result
    monkeypatch.setattr(fake_predictor, "predict", predict_and_change)
    response = workspace.client.post(f"/api/samples/{workspace.sample_id}/sam/predict", json=prompts())
    assert response.status_code == 409
    assert workspace.service._image_key is None


def test_empty_mask_does_not_create_an_annotation(workspace, fake_predictor, monkeypatch):
    import numpy as np
    monkeypatch.setattr(fake_predictor, "predict", lambda **kwargs: (np.zeros((1, 60, 80), dtype=bool), np.array([.8]), None))
    response = workspace.client.post(f"/api/samples/{workspace.sample_id}/sam/predict", json=prompts())
    assert response.status_code == 422
    assert workspace.client.get(f"/api/samples/{workspace.sample_id}/annotations").json() == []
