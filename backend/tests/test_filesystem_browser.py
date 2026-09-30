from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_file_browser_filters_json_and_opens_file_parent(tmp_path: Path) -> None:
    (tmp_path / "子目录").mkdir()
    source = tmp_path / "标注.JSON"
    source.write_text('{"test": true}', encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"image")
    before = source.read_bytes()
    client = TestClient(app)

    for path in (tmp_path, source):
        response = client.get("/api/filesystem/entries", params={"path": str(path)})
        assert response.status_code == 200
        body = response.json()
        assert body["current_path"] == str(tmp_path.resolve())
        assert body["entries"] == [
            {"name": "子目录", "path": str((tmp_path / "子目录").resolve()), "kind": "directory"},
            {"name": "标注.JSON", "path": str(source.resolve()), "kind": "file"},
        ]

    directories = client.get("/api/filesystem/directories", params={"path": str(tmp_path)}).json()
    assert [entry["name"] for entry in directories["entries"]] == ["子目录"]
    assert source.read_bytes() == before
    assert client.get("/api/filesystem/entries", params={"path": str(tmp_path / "missing")}).status_code == 404
    assert client.get("/api/filesystem/entries").status_code == 200


def test_file_browser_reports_unreadable_directory(tmp_path: Path, monkeypatch) -> None:
    def denied(_path: Path):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "iterdir", denied)
    response = TestClient(app).get("/api/filesystem/entries", params={"path": str(tmp_path)})
    assert response.status_code == 403
