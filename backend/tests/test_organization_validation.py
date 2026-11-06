from sqlmodel import Session, select
from app.models.organization import DatasetCategory
from app.models.sample import Sample
from test_validation_execution import workspace


def test_single_class_baseline_rejects_mixed_object_categories_and_accepts_scoped_query(tmp_path, monkeypatch):
    client, engine, dataset = workspace(tmp_path, monkeypatch)
    with Session(engine) as session:
        first = DatasetCategory(dataset_id=dataset['id'], name='first-object')
        second = DatasetCategory(dataset_id=dataset['id'], name='second-object')
        session.add_all([first, second]); session.flush()
        first_id = first.id
        samples = session.exec(select(Sample).where(Sample.dataset_id == dataset['id']).order_by(Sample.id)).all()
        for index, sample in enumerate(samples):
            sample.category_id = first.id if index < 8 else second.id
            session.add(sample)
        session.commit()
    endpoint = f"/api/datasets/{dataset['id']}/validation/previews"
    response = client.post(endpoint, json={})
    assert response.status_code == 200, response.text
    assert any('单一对象类别' in message for message in response.json()['summary']['blockers'])
    scoped = client.post(endpoint, json={'protocol': {'sample_query': {'category_id': first_id}}})
    assert scoped.status_code == 200, scoped.text
    assert not any('单一对象类别' in message for message in scoped.json()['summary']['blockers'])
    assert len(scoped.json()['rows']) == 8


def test_official_test_images_cannot_enter_baseline_fitting(tmp_path, monkeypatch):
    client, engine, dataset = workspace(tmp_path, monkeypatch)
    with Session(engine) as session:
        for sample in session.exec(select(Sample).where(Sample.dataset_id == dataset['id'])).all():
            sample.official_split = 'test'
            session.add(sample)
        session.commit()
    response = client.post(f"/api/datasets/{dataset['id']}/validation/previews", json={})
    assert response.status_code == 200, response.text
    assert any('官方测试图片' in message for message in response.json()['summary']['blockers'])


def test_legacy_capture_mapping_rejects_ambiguous_paths_from_multiple_sources(tmp_path, monkeypatch):
    from app.schemas.industrial import GroupPreviewRequest
    from app.services import capture_group_service
    from fastapi import HTTPException
    import pytest
    client, engine, dataset = workspace(tmp_path, monkeypatch)
    with Session(engine) as session:
        sample = session.exec(select(Sample).where(Sample.dataset_id == dataset['id']).order_by(Sample.id)).first()
        session.add(Sample(dataset_id=dataset['id'], filename=sample.filename, relative_path=sample.relative_path,
            absolute_path='/another-source/' + sample.relative_path, extension='.png', file_type='image', file_hash=sample.file_hash))
        session.commit()
        with pytest.raises(HTTPException, match='多个来源'):
            capture_group_service.preview(session, dataset['id'], GroupPreviewRequest(mode='mapping', mapping_text='relative_path,capture_group_id,capture_batch_id\n' + sample.relative_path + ',part-a,batch-a\n'))
