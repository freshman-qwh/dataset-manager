from __future__ import annotations

import json
import socket
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import system
from app.core import config
from app.core.portable import (
    DEFAULT_PORT,
    PortableController,
    load_preferred_port,
    prepare_data_paths,
    read_runtime_file,
    remove_runtime_file,
    resolve_data_root,
    write_runtime_file,
)
from app.core.static_frontend import install_frontend
from portable_launcher import _bind_available_port


def test_portable_paths_support_chinese_and_spaces(tmp_path: Path) -> None:
    local_app_data = tmp_path / "本地 应用数据"
    root = resolve_data_root({"LOCALAPPDATA": str(local_app_data)})
    paths = prepare_data_paths(root)

    assert root == (local_app_data / "DatasetManager").resolve()
    assert paths.database == root / "database" / "app.db"
    assert paths.settings_file.parent.is_dir()
    assert paths.logs.is_dir()
    assert paths.cache.is_dir()
    assert paths.exports.is_dir()
    assert paths.storage.is_dir()


def test_portable_settings_ignore_repository_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "便携 数据"
    monkeypatch.setenv("DATASET_MANAGER_PORTABLE", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(root / 'database/app.db').as_posix()}")
    monkeypatch.setenv("STORAGE_ROOT", str(root / "storage"))
    config.get_settings.cache_clear()
    try:
        settings = config.get_settings()
        assert settings.database_path == (root / "database" / "app.db").resolve()
        assert settings.storage_root == (root / "storage").resolve()
    finally:
        config.get_settings.cache_clear()


def test_runtime_file_is_atomic_and_instance_owned(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    write_runtime_file(path, port=8765, process_id=42, instance_id="first")
    assert read_runtime_file(path) == {
        "application": "dataset-manager",
        "url": "http://127.0.0.1:8765",
        "port": 8765,
        "pid": 42,
        "instance_id": "first",
    }

    remove_runtime_file(path, "different")
    assert path.exists()
    remove_runtime_file(path, "first")
    assert not path.exists()


def test_invalid_port_setting_falls_back(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"preferred_port": 80}), encoding="utf-8")
    assert load_preferred_port(settings) == DEFAULT_PORT
    settings.write_text(json.dumps({"preferred_port": 9123}), encoding="utf-8")
    assert load_preferred_port(settings) == 9123


def test_port_conflict_chooses_next_available_port() -> None:
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen(1)
    port = occupied.getsockname()[1]
    listener = None
    try:
        listener, selected = _bind_available_port(port, 2)
        assert selected == port + 1
    finally:
        occupied.close()
        if listener is not None:
            listener.close()


def test_static_frontend_serves_assets_spa_and_keeps_api_404(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<main>portable app</main>", encoding="utf-8")
    (frontend / "assets" / "app.js").write_text("window.ready=true", encoding="utf-8")
    app = FastAPI()
    assert install_frontend(app, frontend) is True

    with TestClient(app) as client:
        assert client.get("/").text == "<main>portable app</main>"
        assert client.get("/datasets/1").text == "<main>portable app</main>"
        assert client.get("/assets/app.js").text == "window.ready=true"
        assert client.get("/api/missing").status_code == 404


def test_portable_system_actions_are_explicit(monkeypatch, tmp_path: Path) -> None:
    controller = PortableController()
    stopped: list[bool] = []
    opened: list[str] = []
    controller.configure(
        data_root=tmp_path,
        port=8765,
        control_token="test-control-token",
        shutdown=lambda: stopped.append(True),
    )
    monkeypatch.setattr(system, "portable_controller", controller)
    monkeypatch.setattr("app.core.portable.os.startfile", lambda path: opened.append(path))
    app = FastAPI()
    app.include_router(system.router)

    with TestClient(app) as client:
        runtime = client.get("/api/system/portable-runtime")
        assert runtime.status_code == 200
        assert runtime.json()["enabled"] is True
        assert client.post("/api/system/portable-runtime/shutdown").status_code == 403
        headers = {"X-Dataset-Manager-Control-Token": "test-control-token"}
        assert client.post("/api/system/portable-runtime/open-data-directory", headers=headers).status_code == 204
        assert client.post("/api/system/portable-runtime/shutdown", headers=headers).status_code == 202

    assert opened == [str(tmp_path.resolve())]
    # The timer is intentionally asynchronous so the HTTP response can flush.
    for timer in list(__import__("threading").enumerate()):
        if isinstance(timer, __import__("threading").Timer):
            timer.join(timeout=1)
    assert stopped == [True]
