import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

DEFAULT_ALLOWED_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]


class Settings(BaseModel):
    app_name: str = "Dataset Manager"
    debug: bool = False
    database_url: str
    database_path: Path
    storage_root: Path
    allowed_origins: list[str] = Field(default_factory=lambda: DEFAULT_ALLOWED_ORIGINS.copy())


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_local_path(value: str | None, default: Path) -> Path:
    if not value:
        return default.resolve()

    raw_path = Path(value)
    if raw_path.is_absolute():
        return raw_path.resolve()

    # Existing .env examples are written for commands executed from backend/.
    base = _backend_root() if value.startswith("..") else _project_root()
    return (base / raw_path).resolve()


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


@lru_cache
def get_settings() -> Settings:
    root = _project_root()
    load_dotenv(root / ".env")
    load_dotenv(_backend_root() / ".env", override=True)

    storage_root = _resolve_local_path(
        os.getenv("STORAGE_ROOT"),
        root / "storage",
    )

    database_env = os.getenv("DATABASE_URL")
    if database_env and database_env.startswith("sqlite:///"):
        database_value = database_env.removeprefix("sqlite:///")
        database_path = _resolve_local_path(database_value, root / "database" / "app.db")
    else:
        database_path = root / "database" / "app.db"

    origins_env = os.getenv("CORS_ORIGINS", "")
    origins = [origin.strip() for origin in origins_env.split(",") if origin.strip()]

    return Settings(
        app_name=os.getenv("APP_NAME", "Dataset Manager"),
        debug=os.getenv("APP_ENV", "dev").lower() == "dev",
        database_url=_sqlite_url(database_path),
        database_path=database_path,
        storage_root=storage_root,
        allowed_origins=origins or DEFAULT_ALLOWED_ORIGINS.copy(),
    )
