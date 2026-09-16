from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
import logging
import os
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from uuid import uuid4


MUTEX_NAME = "Local\\DatasetManager.Portable"
ERROR_ALREADY_EXISTS = 183
HOST = "127.0.0.1"


class SingleInstance:
    def __init__(self) -> None:
        self.handle: int | None = None

    def acquire(self) -> bool:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.SetLastError(0)
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            raise ctypes.WinError()
        self.handle = handle
        return kernel32.GetLastError() != ERROR_ALREADY_EXISTS

    def close(self) -> None:
        if self.handle:
            ctypes.windll.kernel32.CloseHandle(self.handle)  # type: ignore[attr-defined]
            self.handle = None


def _configure_environment(data_root: Path) -> None:
    os.environ["DATASET_MANAGER_PORTABLE"] = "1"
    os.environ["DATASET_MANAGER_DATA_ROOT"] = str(data_root)
    os.environ["DATABASE_URL"] = f"sqlite:///{(data_root / 'database' / 'app.db').as_posix()}"
    os.environ["STORAGE_ROOT"] = str(data_root / "storage")
    os.environ["APP_ENV"] = "portable"
    os.environ["CORS_ORIGINS"] = "http://127.0.0.1"
    if getattr(sys, "frozen", False):
        os.environ["DATASET_MANAGER_FRONTEND_DIR"] = str(
            Path(getattr(sys, "_MEIPASS")) / "frontend"
        )


def _configure_logging(log_file: Path) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
        force=True,
    )


def _health_ok(url: str, timeout: float = 0.7) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=timeout) as response:
            return response.status == 200 and b'"application":"dataset-manager"' in response.read()
    except (OSError, urllib.error.URLError):
        return False


def _open_existing(runtime_file: Path) -> bool:
    from app.core.portable import read_runtime_file

    state = read_runtime_file(runtime_file)
    url = state.get("url") if state else None
    if isinstance(url, str) and _health_ok(url):
        if os.getenv("DATASET_MANAGER_NO_BROWSER") != "1":
            webbrowser.open(url)
        return True
    return False


def _bind_available_port(preferred: int, count: int) -> tuple[socket.socket, int]:
    for port in range(preferred, min(preferred + count, 65536)):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((HOST, port))
            listener.listen(2048)
            return listener, port
        except OSError:
            listener.close()
    raise RuntimeError(f"端口 {preferred}–{preferred + count - 1} 均被占用")


def _open_browser_when_ready(url: str) -> None:
    for _ in range(100):
        if _health_ok(url):
            if os.getenv("DATASET_MANAGER_NO_BROWSER") != "1":
                webbrowser.open(url)
            return
        time.sleep(0.1)


def run() -> int:
    from app.core.portable import (
        PORT_SCAN_LIMIT,
        load_preferred_port,
        portable_controller,
        prepare_data_paths,
        remove_runtime_file,
        write_runtime_file,
    )

    paths = prepare_data_paths()
    _configure_environment(paths.root)
    _configure_logging(paths.logs / "dataset-manager.log")
    instance = SingleInstance()
    if not instance.acquire():
        _open_existing(paths.runtime_file)
        instance.close()
        return 0

    instance_id = uuid4().hex
    listener: socket.socket | None = None
    try:
        from app.core.migrations import recover_database_after_unclean_shutdown, upgrade_database

        recover_database_after_unclean_shutdown(paths.database)
        upgrade_database(paths.database, paths.backups)
        listener, port = _bind_available_port(
            load_preferred_port(paths.settings_file),
            PORT_SCAN_LIMIT,
        )
        url = f"http://{HOST}:{port}"
        write_runtime_file(
            paths.runtime_file,
            port=port,
            process_id=os.getpid(),
            instance_id=instance_id,
        )

        import uvicorn

        from app.core.portable import portable_controller
        from app.main import app

        config = uvicorn.Config(
            app,
            host=HOST,
            port=port,
            log_config=None,
            access_log=False,
        )
        server = uvicorn.Server(config)
        portable_controller.configure(
            data_root=paths.root,
            port=port,
            control_token=instance_id,
            shutdown=lambda: setattr(server, "should_exit", True),
        )
        signal.signal(signal.SIGTERM, lambda *_args: setattr(server, "should_exit", True))
        threading.Thread(
            target=_open_browser_when_ready,
            args=(url,),
            daemon=True,
        ).start()
        asyncio.run(server.serve(sockets=[listener]))
        return 0
    except Exception as exc:
        logging.exception("Dataset Manager portable startup failed")
        try:
            ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                None,
                f"Dataset Manager 启动失败。\n\n{exc}\n\n详细信息已写入日志目录。",
                "Dataset Manager",
                0x10,
            )
        except Exception:
            pass
        return 1
    finally:
        portable_controller.reset()
        remove_runtime_file(paths.runtime_file, instance_id)
        if listener is not None:
            listener.close()
        instance.close()


if __name__ == "__main__":
    raise SystemExit(run())
