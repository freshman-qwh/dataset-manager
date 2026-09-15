from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping
from uuid import uuid4


APP_DATA_DIR_NAME = "DatasetManager"
DEFAULT_PORT = 8765
PORT_SCAN_LIMIT = 20


@dataclass(frozen=True)
class PortablePaths:
    root: Path
    database: Path
    config: Path
    logs: Path
    cache: Path
    exports: Path
    storage: Path
    backups: Path
    runtime_file: Path
    settings_file: Path


def resolve_data_root(environ: Mapping[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    explicit = values.get("DATASET_MANAGER_DATA_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve()
    local_app_data = values.get("LOCALAPPDATA")
    if local_app_data:
        return (Path(local_app_data) / APP_DATA_DIR_NAME).resolve()
    return (Path.home() / "AppData" / "Local" / APP_DATA_DIR_NAME).resolve()


def prepare_data_paths(root: Path | None = None) -> PortablePaths:
    data_root = (root or resolve_data_root()).resolve()
    paths = PortablePaths(
        root=data_root,
        database=data_root / "database" / "app.db",
        config=data_root / "config",
        logs=data_root / "logs",
        cache=data_root / "cache",
        exports=data_root / "exports",
        storage=data_root / "storage",
        backups=data_root / "database" / "backups",
        runtime_file=data_root / "config" / "runtime.json",
        settings_file=data_root / "config" / "settings.json",
    )
    for directory in (
        paths.database.parent,
        paths.config,
        paths.logs,
        paths.cache,
        paths.exports,
        paths.storage,
        paths.backups,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return paths


def load_preferred_port(settings_file: Path) -> int:
    try:
        payload = json.loads(settings_file.read_text(encoding="utf-8"))
        value = int(payload.get("preferred_port", DEFAULT_PORT))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return DEFAULT_PORT
    return value if 1024 <= value <= 65535 else DEFAULT_PORT


def write_runtime_file(
    path: Path,
    *,
    port: int,
    process_id: int,
    instance_id: str,
) -> None:
    payload = {
        "application": "dataset-manager",
        "url": f"http://127.0.0.1:{port}",
        "port": port,
        "pid": process_id,
        "instance_id": instance_id,
    }
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_runtime_file(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("application") != "dataset-manager":
        return None
    return payload


def remove_runtime_file(path: Path, instance_id: str) -> None:
    payload = read_runtime_file(path)
    if payload is not None and payload.get("instance_id") == instance_id:
        path.unlink(missing_ok=True)


@dataclass
class PortableRuntime:
    enabled: bool = False
    data_root: str | None = None
    url: str | None = None
    port: int | None = None
    pid: int | None = None
    control_token: str | None = None


class PortableController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runtime = PortableRuntime()
        self._shutdown: Callable[[], None] | None = None

    def configure(
        self,
        *,
        data_root: Path,
        port: int,
        control_token: str,
        shutdown: Callable[[], None],
    ) -> None:
        with self._lock:
            self._runtime = PortableRuntime(
                enabled=True,
                data_root=str(data_root.resolve()),
                url=f"http://127.0.0.1:{port}",
                port=port,
                pid=os.getpid(),
                control_token=control_token,
            )
            self._shutdown = shutdown

    def reset(self) -> None:
        with self._lock:
            self._runtime = PortableRuntime()
            self._shutdown = None

    def describe(self) -> dict[str, str | int | bool | None]:
        with self._lock:
            return asdict(self._runtime)

    def _authorize(self, control_token: str | None) -> None:
        if not control_token or control_token != self._runtime.control_token:
            raise PermissionError("便携版控制令牌无效")

    def open_data_directory(self, control_token: str | None) -> None:
        with self._lock:
            self._authorize(control_token)
            root = self._runtime.data_root
        if root is None:
            raise RuntimeError("当前不是便携版运行模式")
        os.startfile(root)  # type: ignore[attr-defined]

    def request_shutdown(self, control_token: str | None) -> None:
        with self._lock:
            self._authorize(control_token)
            callback = self._shutdown
        if callback is None:
            raise RuntimeError("当前不是便携版运行模式")
        threading.Timer(0.25, callback).start()


portable_controller = PortableController()
