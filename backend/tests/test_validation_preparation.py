import hashlib
import json
from pathlib import Path

from PIL import Image
from sqlmodel import Session
from app.models.dataset import Dataset
from app.services import validation_plan_service
from test_validation_execution import workspace


def test_roi_is_versioned_metadata_and_frozen_per_experiment(tmp_path, monkeypatch):
    client,engine,dataset = workspace(tmp_path,monkeypatch)
    base=f"/api/datasets/{dataset['id']}/validation"
    original=client.get(base+"/settings").json()
    plan=client.post(base+"/previews",json={}).json()
    with Session(engine) as session:
        stored=session.get(Dataset,dataset["id"])
        stored.industrial_settings_json=json.dumps({"filename_group_rule":{"delimiter":"_","keep_segments":2}})
        session.add(stored);session.commit()
    roi=dict(x=.2,y=.1,width=.6,height=.8)
    saved=client.put(base+"/settings",json={"roi":roi,"expected_dataset_revision":original["dataset_revision"]})
    assert saved.status_code==200,saved.text
    value=saved.json();assert value["roi"]==roi and value["dataset_revision"]==original["dataset_revision"]+1
    assert client.get(f"/api/datasets/{dataset['id']}/industrial/group-rule").json()["keep_segments"]==2
    assert client.put(base+"/settings",json={"roi":roi,"expected_dataset_revision":original["dataset_revision"]}).status_code==409
    assert client.put(base+"/settings",json={"roi":roi,"expected_dataset_revision":value["dataset_revision"]}).json()["dataset_revision"]==value["dataset_revision"]
    with Session(engine) as session:
        import pytest
        from fastapi import HTTPException
        with pytest.raises(HTTPException): validation_plan_service.validate(session,dataset["id"],plan["plan_id"],plan["plan_hash"])
    small=client.post(base+"/previews",json={"roi":{"x":0,"y":0,"width":.001,"height":.5}}).json()
    assert small["summary"]["blocked"] and any("4" in message for message in small["summary"]["blockers"])
    assert client.post(base+"/previews",json={"roi":{"x":.8,"y":0,"width":.5,"height":1}}).status_code==422


def test_quality_inspection_is_read_only_and_uses_roi(tmp_path,monkeypatch):
    client,engine,dataset=workspace(tmp_path,monkeypatch)
    root=tmp_path/"inspection";root.mkdir()
    image=Image.new("RGB",(64,32),"white");image.paste((0,0,0),(0,0,32,32));image.save(root/"left.png")
    image.save(root/"exact.png")
    Image.new("RGB",(64,32),"black").save(root/"dark.png")
    created=client.post("/api/datasets",json={"name":"quality","workflow_profile":"industrial_anomaly","root_path":str(root)}).json()
    client.post(f"/api/datasets/{created['id']}/scan",json={"folder_path":str(root)})
    before=client.get(f"/api/datasets/{created['id']}/samples").json()
    hashes={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
    endpoint=f"/api/datasets/{created['id']}/validation/quality-inspections"
    response=client.post(endpoint,json={});assert response.status_code==200,response.text
    report=response.json();assert report["processed"]==3 and report["failed"]==0
    assert any(pair["exact_duplicate"] for pair in report["pairs"])
    assert all(row["sharpness"] is not None for row in report["images"])
    roi_report=client.post(endpoint,json={"roi":{"x":0,"y":0,"width":.4,"height":1}}).json()
    assert all(row["brightness"]==0 for row in roi_report["images"])
    assert all("偏暗候选" in row["issues"] for row in roi_report["images"])
    assert client.get(f"/api/datasets/{created['id']}/samples").json()==before
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==digest for p,digest in hashes.items())
    assert client.post(endpoint,json={"sample_query":{"sample_ids":[999999]}}).status_code==422
    from app.services import validation_preparation_service as prep
    monkeypatch.setattr(prep.sample_service,"get_filtered_samples",lambda *args,**kwargs:[None]*301)
    assert client.post(endpoint,json={}).status_code==422
