"""Read-only benchmark layouts; semantic metadata is applied only to new images."""
from collections import Counter
from collections.abc import Callable
import csv
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from fastapi import HTTPException
from PIL import Image

from app.schemas.scan import ImportPreview
from app.utils.file_types import detect_file_type

VISA_CATEGORIES = {"candle", "capsules", "cashew", "chewinggum", "fryum", "macaroni1", "macaroni2", "pcb1", "pcb2", "pcb3", "pcb4", "pipe_fryum"}

@dataclass(frozen=True)
class BenchmarkImage:
    category: str
    label: str
    split: str | None = None
    defect: str | None = None
    mask_path: str | None = None


@dataclass
class BenchmarkInventory:
    format: str
    images: dict[str, BenchmarkImage] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def preview(self) -> ImportPreview:
        return ImportPreview(
            detected_format=self.format,
            categories=sorted({row.category for row in self.images.values()}),
            image_count=len(self.images),
            mask_count=sum(row.mask_path is not None for row in self.images.values()),
            warnings=self.warnings[:50],
            official_split_counts=dict(Counter(row.split for row in self.images.values() if row.split)),
        )


def _inside(root: Path, value: str, *, base: Path | None = None) -> Path:
    normalized = value.replace("\\", "/")
    parts = PurePosixPath(normalized)
    if parts.is_absolute() or ":" in normalized or any(part == ".." for part in parts.parts):
        raise HTTPException(422, "官方索引包含越界路径，请检查导入文件。")
    result = ((base or root) / normalized).resolve()
    if not result.is_relative_to(root.resolve()):
        raise HTTPException(422, "官方索引路径不在所选数据集目录内。")
    return result


def _image_files(directory: Path, root: Path, checkpoint: Callable[[], None]):
    for path in sorted(directory.rglob("*")):
        checkpoint()
        if path.is_file() and detect_file_type(path) == "image":
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                raise HTTPException(422, "图片链接指向所选数据集之外，请检查目录。")
            yield resolved


def _mask(image: Path, candidate: Path | None, inventory: BenchmarkInventory) -> str | None:
    if candidate is None or not candidate.is_file():
        inventory.warnings.append(f"异常图缺少 mask：{image.name}")
        return None
    try:
        with Image.open(image) as original, Image.open(candidate) as mask:
            if original.size != mask.size:
                raise ValueError("图片与 mask 尺寸不一致")
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        inventory.warnings.append(f"未关联 mask {candidate.name}：{exc}")
        return None
    return str(candidate.resolve())


def _category_roots(root: Path) -> list[Path]:
    if (root / "train").is_dir() and (root / "test").is_dir():
        return [root]
    return sorted(path for path in root.iterdir() if path.is_dir() and (path / "train").is_dir() and (path / "test").is_dir())


def _structured(root: Path, format: str, checkpoint: Callable[[], None]) -> BenchmarkInventory:
    inventory = BenchmarkInventory(format)
    actual_root = root / "1cls" if format == "visa" and (root / "1cls").is_dir() else root
    for category in _category_roots(actual_root):
        for split in ("train", "test"):
            for kind in sorted((category / split).iterdir()):
                if not kind.is_dir():
                    continue
                normal = kind.name == "good"
                for path in _image_files(kind, root, checkpoint):
                    mask_path = None
                    if not normal:
                        mask_root = category / "ground_truth" / kind.name
                        candidates = [mask_root / (path.stem + "_mask.png"), mask_root / (path.stem + ".png"), mask_root / path.name]
                        candidate = next((candidate for candidate in candidates if candidate.is_file()), None)
                        if candidate and not candidate.resolve().is_relative_to(root):
                            raise HTTPException(422, "mask 链接指向所选数据集之外。")
                        mask_path = _mask(path, candidate, inventory)
                    inventory.images[str(path)] = BenchmarkImage(category.name, "normal" if normal else "anomaly", split,
                        None if normal else kind.name, mask_path)
    return inventory


def _csv_rows(path: Path):
    try:
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames or not {"label", "image"}.issubset(reader.fieldnames):
                raise HTTPException(422, f"VisA 索引缺少 label/image 列：{path.name}")
            yield from reader
    except (OSError, UnicodeError, csv.Error) as exc:
        raise HTTPException(422, f"无法读取 VisA 索引：{path.name}") from exc


def _raw_visa(root: Path, checkpoint: Callable[[], None]) -> BenchmarkInventory:
    inventory = BenchmarkInventory("visa")
    raw_categories = [root] if (root / "Data/Images").is_dir() else sorted(p for p in root.iterdir() if p.is_dir() and (p / "Data/Images").is_dir())
    for category in raw_categories:
        for kind, label in (("Normal", "normal"), ("Anomaly", "anomaly")):
            directory = category / "Data/Images" / kind
            if not directory.is_dir():
                continue
            for image in _image_files(directory, root, checkpoint):
                candidate = category / "Data/Masks/Anomaly" / (image.stem + ".png")
                if not candidate.resolve().is_relative_to(root):
                    raise HTTPException(422, "mask 链接指向所选数据集之外。")
                mask_path = _mask(image, candidate, inventory) if label == "anomaly" else None
                inventory.images[str(image)] = BenchmarkImage(category.name, label, None, "anomaly" if label == "anomaly" else None, mask_path)

    local_index = root / "split_csv/1cls.csv"
    # The official 2022 single-class protocol is bundled as small metadata only.
    index = local_index if local_index.is_file() else Path(__file__).resolve().parents[1] / "data/visa/1cls.csv"
    bundled = index != local_index
    if bundled:
        inventory.warnings.append("使用随软件附带的 VisA 官方 1cls 划分索引；仅匹配本地存在的图片，未随机重划分。")
    indexed: dict[str, BenchmarkImage] = {}
    missing_rows = 0
    for row in _csv_rows(index):
        checkpoint()
        category_name = str(row.get("object") or row.get("category") or "").strip()
        image_value = str(row.get("image") or "").strip()
        raw_mask_value = str(row.get("mask") or "").strip()
        label = str(row.get("label") or "").strip().lower()
        split = str(row.get("split") or "").strip().lower()
        if not image_value or not category_name:
            raise HTTPException(422, "VisA 官方索引缺少对象名或图片路径。")
        if label not in {"normal", "anomaly"} or split not in {"train", "test"}:
            raise HTTPException(422, "VisA 官方划分索引包含未知 label 或 split。")
        # Selecting a single object directory is supported, but index paths are
        # still validated as relative paths before stripping its category prefix.
        relative = PurePosixPath(image_value.replace("\\", "/"))
        if relative.is_absolute() or ":" in image_value or ".." in relative.parts:
            raise HTTPException(422, "VisA 索引包含越界图片路径。")
        mask_parts = PurePosixPath(raw_mask_value.replace("\\", "/"))
        if mask_parts.is_absolute() or ":" in raw_mask_value or ".." in mask_parts.parts:
            raise HTTPException(422, "VisA 索引包含越界 mask 路径。")
        if (root / "Data/Images").is_dir():
            if not relative.parts or relative.parts[0] != root.name:
                missing_rows += 1
                continue
            image_value = "/".join(relative.parts[1:])
        image = _inside(root, image_value)
        key = str(image)
        original = inventory.images.get(key)
        if original is None:
            missing_rows += 1
            continue
        if label != original.label or category_name != original.category:
            raise HTTPException(422, f"VisA 索引类别/判定与目录不一致：{image.name}")
        if key in indexed:
            raise HTTPException(422, f"VisA 官方索引重复登记图片：{image.name}")
        mask_value = raw_mask_value
        mask_path = original.mask_path
        if label == "normal" and mask_value:
            raise HTTPException(422, "VisA 正常图片不应关联异常 mask。")
        if label == "anomaly" and mask_value:
            if (root / "Data/Images").is_dir():
                mask_parts = PurePosixPath(mask_value.replace("\\", "/"))
                if not mask_parts.parts or mask_parts.parts[0] != root.name:
                    raise HTTPException(422, "VisA mask 类别与图片不一致。")
                mask_value = "/".join(mask_parts.parts[1:])
            candidate = _inside(root, mask_value)
            mask_path = _mask(image, candidate, inventory)
        indexed[key] = BenchmarkImage(original.category, original.label, split, original.defect, mask_path)
    inventory.images.update(indexed)
    if missing_rows:
        inventory.warnings.append(f"官方索引中有 {missing_rows} 张图片不在当前本地子集，已跳过。")
    unmatched = len(inventory.images) - len(indexed)
    if unmatched:
        inventory.warnings.append(f"{unmatched} 张本地图片未匹配官方索引，保留目录标签但不设置官方划分。")
    return inventory


def inspect_benchmark(root: Path, requested: str = "auto", checkpoint: Callable[[], None] | None = None) -> BenchmarkInventory:
    root = root.resolve()
    check = checkpoint or (lambda: None)
    if requested == "folder":
        return BenchmarkInventory("folder")
    try:
        raw_visa = (root / "Data/Images").is_dir() or any(p.is_dir() and (p / "Data/Images").is_dir() for p in root.iterdir())
        roots = _category_roots(root)
        prepared_visa = ((root / "1cls").is_dir() or root.name == "1cls" or root.parent.name == "1cls"
            or bool(roots) and all(category.name in VISA_CATEGORIES for category in roots)
            and any((category / "test/bad").is_dir() for category in roots))
        structured = any((category / "train/good").is_dir() for category in _category_roots(root))
        detected = "visa" if raw_visa or prepared_visa else "mvtec_ad" if structured else "folder"
        if requested != "auto":
            detected = requested
        if detected == "folder":
            return BenchmarkInventory("folder")
        inventory = _raw_visa(root, check) if detected == "visa" and raw_visa else _structured(root, detected, check)
        if not inventory.images:
            raise HTTPException(422, "没有识别到该格式的图片，请选择数据集根目录或改用普通文件夹。")
        return inventory
    except OSError as exc:
        raise HTTPException(422, f"无法检查数据集目录：{exc}") from exc
