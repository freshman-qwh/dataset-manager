from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.database import get_session
from app.main import app
from app.models.dataset import Dataset
from app.models.sample import Sample


@pytest.fixture
def browse_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        dataset = Dataset(name="Folder collection", root_path="/not-mounted/originals")
        other = Dataset(name="Other collection")
        empty = Dataset(name="Empty collection")
        session.add_all([dataset, other, empty])
        session.flush()
        ids = dataset.id, other.id, empty.id
        for relative_path, kind in [
            ("root.png", "image"), ("readme.csv", "csv"),
            ("a/one.png", "image"), ("a/deeper/two.png", "image"),
            ("ab/sibling.png", "image"), ("工件%_甲/原图.png", "image"),
            ("工件%_甲/meta.csv", "csv"), ("工件XX甲/other.png", "image"),
            ("legacy\\nested\\old.png", "image"),
        ]:
            session.add(Sample(dataset_id=dataset.id, filename=relative_path.replace("\\", "/").split("/")[-1],
                absolute_path="/not-mounted/originals/" + relative_path,
                relative_path=relative_path, file_type=kind, extension=".png" if kind == "image" else ".csv",
                file_hash="a" * 64))
        session.add(Sample(dataset_id=other.id, filename="private.png", absolute_path="/other/a/private.png",
            relative_path="a/private.png", file_type="image", extension=".png", file_hash="b" * 64))
        session.commit()

    def override_session():
        with Session(engine) as session:
            yield session

    old_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app), engine, ids
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old_overrides)
        engine.dispose()


def test_browse_nested_folders_and_recursive_image_view(browse_client):
    client, _, (dataset_id, _, _) = browse_client
    root = client.get(f"/api/datasets/{dataset_id}/browse").json()
    assert [item["relative_path"] for item in root["items"]] == ["readme.csv", "root.png"]
    groups = {folder["name"]: folder for folder in root["folders"]}
    assert groups["a"]["sample_count"] == groups["a"]["image_count"] == 2
    assert groups["a"]["cover_sample_id"] is not None
    assert groups["a"]["cover_file_hash"] == "a" * 64
    assert groups["工件%_甲"]["sample_count"] == 2
    assert groups["工件%_甲"]["image_count"] == 1
    direct = client.get(f"/api/datasets/{dataset_id}/browse", params={"folder": "a"}).json()
    assert [item["filename"] for item in direct["items"]] == ["one.png"]
    assert [folder["path"] for folder in direct["folders"]] == ["a/deeper"]
    recursive = client.get(f"/api/datasets/{dataset_id}/browse", params={"folder": "a", "recursive": True}).json()
    assert [item["filename"] for item in recursive["items"]] == ["two.png", "one.png"]
    assert recursive["total"] == 2
    images = client.get(f"/api/datasets/{dataset_id}/browse", params={"recursive": True, "file_type": "image"}).json()
    assert images["total"] == 7
    assert all(item["file_type"] == "image" for item in images["items"])


def test_browse_literal_search_folder_boundaries_and_windows_separators(browse_client):
    client, _, (dataset_id, _, _) = browse_client
    special = client.get(f"/api/datasets/{dataset_id}/browse", params={"folder": "工件%_甲/", "search": "原图"}).json()
    assert special["folder"] == "工件%_甲"
    assert special["total"] == 1
    literal = client.get(f"/api/datasets/{dataset_id}/browse", params={"search": "%_", "recursive": True}).json()
    assert literal["total"] == 2
    nested = client.get(f"/api/datasets/{dataset_id}/browse", params={"folder": "legacy\\nested"}).json()
    assert nested["folder"] == "legacy/nested"
    assert [item["filename"] for item in nested["items"]] == ["old.png"]
    assert "private.png" not in str(nested)
    # Folder counts do not disappear merely because a file search is active.
    filtered = client.get(f"/api/datasets/{dataset_id}/browse", params={"search": "not-found", "file_type": "video"}).json()
    assert filtered["total"] == 0
    assert filtered["folders_total"] == 5


def test_browse_page_bounds_empty_and_unknown_dataset(browse_client):
    client, _, (dataset_id, _, empty_id) = browse_client
    first = client.get(f"/api/datasets/{dataset_id}/browse", params={"recursive": True, "page_size": 2, "folder_page_size": 2}).json()
    last = client.get(f"/api/datasets/{dataset_id}/browse", params={"recursive": True, "page_size": 2, "page": 999, "folder_page": 999, "folder_page_size": 2}).json()
    assert len(first["items"]) == len(first["folders"]) == 2
    assert last["page"] == 5 and len(last["items"]) == 1
    assert last["folder_page"] == 3 and len(last["folders"]) == 1
    assert not ({item["id"] for item in first["items"]} & {item["id"] for item in last["items"]})
    empty = client.get(f"/api/datasets/{empty_id}/browse").json()
    assert empty["items"] == empty["folders"] == []
    assert empty["total"] == empty["folders_total"] == 0
    assert client.get("/api/datasets/999999/browse").status_code == 404
    for params in [{"page": 0}, {"page_size": 201}, {"folder_page_size": 201}, {"folder_page": 0}]:
        assert client.get(f"/api/datasets/{dataset_id}/browse", params=params).status_code == 422


@pytest.mark.parametrize("folder", ["../a", "a/../b", "/absolute", "C:\\data", "C:data", "\\\\server\\share", "a/./b", "bad\x00path"])
def test_browse_rejects_nonrelative_folder(browse_client, folder):
    client, _, (dataset_id, _, _) = browse_client
    assert client.get(f"/api/datasets/{dataset_id}/browse", params={"folder": folder}).status_code == 422


def test_browse_does_not_access_raw_disk_or_change_metadata_and_bounds_orm_loads(browse_client, monkeypatch):
    client, engine, (dataset_id, _, _) = browse_client
    with Session(engine) as session:
        before = [(s.id, s.relative_path, s.updated_at) for s in session.exec(select(Sample)).all()]
        revision = session.get(Dataset, dataset_id).revision
    loaded = []
    def on_load(sample, context):
        loaded.append(sample.id)
    def no_disk(*args, **kwargs):
        raise AssertionError("Browsing must use only registered metadata")
    event.listen(Sample, "load", on_load)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(Path, "iterdir", no_disk)
            patch.setattr(Path, "stat", no_disk)
            response = client.get(f"/api/datasets/{dataset_id}/browse", params={"recursive": True, "page_size": 2})
            assert response.status_code == 200
        assert len(loaded) == 2
    finally:
        event.remove(Sample, "load", on_load)
    with Session(engine) as session:
        after = [(s.id, s.relative_path, s.updated_at) for s in session.exec(select(Sample)).all()]
        assert after == before
        assert session.get(Dataset, dataset_id).revision == revision


def test_browse_separates_same_named_folders_from_scattered_sources(browse_client):
    client, engine, (dataset_id, _, _) = browse_client
    with Session(engine) as session:
        for absolute, relative in [
            ("/external/first/a/same.png", "a/same.png"),
            ("/external/second/a/same.png", "a/same.png"),
            # A nested rescan stores a short relative path but remains in the
            # dataset's main source at its real nested location.
            ("/not-mounted/originals/a/nested/short.png", "short.png"),
            # Repaired legacy records can carry an obsolete relative path.
            ("/external/repaired/current.png", "stale/old.png"),
        ]:
            session.add(Sample(dataset_id=dataset_id, filename=absolute.split("/")[-1],
                absolute_path=absolute, relative_path=relative, extension=".png", file_type="image", file_hash="c" * 64))
        session.commit()
    default = client.get(f"/api/datasets/{dataset_id}/browse", params={"recursive": True}).json()
    assert default["source_root"] == "/not-mounted/originals"
    assert default["total"] == 10
    assert len(default["sources"]) == 4
    nested = client.get(f"/api/datasets/{dataset_id}/browse", params={"folder": "a/nested"}).json()
    assert [row["filename"] for row in nested["items"]] == ["short.png"]
    for source in ["/external/first", "/external/second"]:
        payload = client.get(f"/api/datasets/{dataset_id}/browse", params={"source_root": source, "folder": "a"}).json()
        assert payload["source_root"] == source
        assert payload["total"] == 1
        assert payload["items"][0]["absolute_path"] == source + "/a/same.png"
    repaired = client.get(f"/api/datasets/{dataset_id}/browse", params={"source_root": "/external/repaired"}).json()
    assert repaired["total"] == 1
    assert repaired["items"][0]["filename"] == "current.png"
    assert client.get(f"/api/datasets/{dataset_id}/browse", params={"source_root": "/unregistered"}).status_code == 404


def test_browse_windows_source_case_normalization_and_posix_case_preservation(browse_client):
    client, engine, (_, _, dataset_id) = browse_client
    with Session(engine) as session:
        for absolute, relative in [
            ("D:\\Data\\first.png", "first.png"),
            ("d:/data/second.png", "second.png"),
            ("//server/Share/one.png", "one.png"),
            ("//SERVER/share/two.png", "two.png"),
            ("/Case/upper.png", "upper.png"),
            ("/case/lower.png", "lower.png"),
            ("D:/Échantillons/accented.png", "accented.png"),
            ("d:/échantillons/other.png", "other.png"),
        ]:
            session.add(Sample(dataset_id=dataset_id, filename=relative, absolute_path=absolute,
                relative_path=relative, extension=".png", file_type="image", file_hash="d" * 64))
        session.commit()
    windows = client.get(f"/api/datasets/{dataset_id}/browse", params={"source_root": "d:\\DATA\\"}).json()
    assert windows["total"] == 2
    assert len(windows["sources"]) == 5
    unicode_source = client.get(f"/api/datasets/{dataset_id}/browse", params={"source_root": "d:/ÉCHANTILLONS"}).json()
    assert unicode_source["total"] == 2
    unc = client.get(f"/api/datasets/{dataset_id}/browse", params={"source_root": "//server/share"}).json()
    assert unc["total"] == 2
    for source in ["/Case", "/case"]:
        posix = client.get(f"/api/datasets/{dataset_id}/browse", params={"source_root": source}).json()
        assert posix["total"] == 1


def test_browse_posix_root_folder_does_not_strip_filename_prefix(browse_client):
    client, engine, (_, _, dataset_id) = browse_client
    with Session(engine) as session:
        dataset = session.get(Dataset, dataset_id)
        dataset.root_path = "/"
        session.add(Sample(dataset_id=dataset_id, filename="root.png", absolute_path="/root.png",
            relative_path="root.png", extension=".png", file_type="image", file_hash="e" * 64))
        session.commit()
    root = client.get(f"/api/datasets/{dataset_id}/browse").json()
    assert root["source_root"] == "/"
    assert root["items"][0]["filename"] == "root.png"
    assert root["folders"] == []


def test_browse_filters_categories_and_batches_without_mixing_datasets(browse_client):
    from app.models.organization import DatasetCategory, DatasetBatch
    client, engine, (dataset_id, other_id, _) = browse_client
    with Session(engine) as session:
        category = DatasetCategory(dataset_id=dataset_id, name="part")
        batch = DatasetBatch(dataset_id=dataset_id, name="first")
        foreign = DatasetCategory(dataset_id=other_id, name="private")
        session.add_all([category, batch, foreign]); session.flush()
        category_id, batch_id, foreign_id = category.id, batch.id, foreign.id
        sample = session.exec(select(Sample).where(Sample.dataset_id == dataset_id, Sample.relative_path == "a/one.png")).one()
        sample.category_id = category_id; sample.batch_id = batch_id
        session.add(sample); session.commit()
    selected = client.get(f"/api/datasets/{dataset_id}/browse", params={"category_id": category_id, "batch_id": batch_id, "recursive": True})
    assert selected.status_code == 200, selected.text
    assert selected.json()["total"] == 1
    assert selected.json()["folders"][0]["sample_count"] == 1
    assert selected.json()["items"][0]["category_id"] == category_id
    assert client.get(f"/api/datasets/{dataset_id}/browse", params={"category_id": foreign_id}).status_code == 422
    with Session(engine) as session:
        session.add(Sample(dataset_id=dataset_id, filename="one.png", absolute_path="/other-root/a/one.png", relative_path="a/one.png", file_type="image", extension=".png", file_hash="c"*64, category_id=category_id, batch_id=batch_id))
        session.commit()
    across = client.get(f"/api/datasets/{dataset_id}/browse", params={"category_id": category_id, "batch_id": batch_id, "all_sources": True}).json()
    assert across["total"] == 2
    assert across["source_root"] == "" and across["folders"] == []
    assert {item["absolute_path"] for item in across["items"]} == {"/other-root/a/one.png", "/not-mounted/originals/a/one.png"}
