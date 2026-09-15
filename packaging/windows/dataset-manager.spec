from pathlib import Path
import os

from PyInstaller.utils.hooks import collect_submodules


repo_root = Path(SPECPATH).parents[1]
backend_root = repo_root / "backend"
frontend_root = Path(os.environ["DATASET_MANAGER_PORTABLE_FRONTEND"]).resolve()

analysis = Analysis(
    [str(backend_root / "portable_launcher.py")],
    pathex=[str(backend_root)],
    binaries=[],
    datas=[
        (str(frontend_root), "frontend"),
        (str(backend_root / "alembic.ini"), "."),
        (str(backend_root / "migrations"), "migrations"),
    ],
    hiddenimports=collect_submodules("uvicorn"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="DatasetManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="x86_64",
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DatasetManager",
)
