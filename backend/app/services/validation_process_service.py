"""Own only the child process created for one optional local task."""
import os
import signal
import subprocess
import time
from pathlib import Path
from collections.abc import Callable


def run_process(command: list[str], log_path: Path, checkpoint: Callable[[], None],
                *, cwd: Path | None = None, env: dict[str, str] | None = None,
                tick: Callable[[], None] | None = None, timeout: int = 7200) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log:
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        process = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=log, env=env, **options)
        started = time.monotonic()
        try:
            while process.poll() is None:
                checkpoint()
                if time.monotonic() - started > timeout:
                    raise TimeoutError("操作超过时限，可缩小数据范围后重试。")
                if tick:
                    tick()
                time.sleep(0.3)
            if process.returncode:
                raise RuntimeError("独立算法进程未完成，请展开诊断日志查看原因；检查组件、权重与数据后可重试。")
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
                else:
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
