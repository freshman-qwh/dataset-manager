"""Read a Dataset Manager image-level package without re-splitting its samples.

Standalone export companion. Anomalib is deliberately imported only on demand.
"""

import argparse
import csv
import hashlib
import json
from collections import Counter
from importlib.metadata import version
from pathlib import Path


def package_rows(root: Path) -> list[dict]:
    root = root.resolve()
    with (root / "samples.csv").open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    seen = set()
    group_splits = {}
    hash_splits = {}
    counts = Counter()
    for row in rows:
        relative = Path(row["image_path"])
        path = (root / relative).resolve()
        if relative.is_absolute() or root not in path.parents:
            raise ValueError("Image path must remain inside the package")
        if row["sample_id"] in seen:
            raise ValueError("Duplicate sample identifier")
        seen.add(row["sample_id"])
        split, label = row["split"], int(row["label_index"])
        if split not in {"train", "val", "test"} or label not in {0, 1}:
            raise ValueError("Invalid split or label")
        if split == "train" and label != 0:
            raise ValueError("Training images must be normal")
        with path.open("rb") as image_file:
            digest = hashlib.file_digest(image_file, "sha256").hexdigest()
        if digest != row["sha256"]:
            raise ValueError(f"Image checksum mismatch: {relative}")
        for key, mapping in ((row["group_id"], group_splits), (digest, hash_splits)):
            if key in mapping and mapping[key] != split:
                raise ValueError("A group or identical image crosses splits")
            mapping[key] = split
        counts[(split, label)] += 1
    if not counts[("train", 0)] or any(not counts[(s, label)] for s in ("val", "test") for label in (0, 1)):
        raise ValueError("A complete protocol needs normal train and both classes in val/test")
    return rows


def create_datamodule(root: Path, batch_size: int = 16, image_size: int = 256):
    if version("anomalib") != "2.7.0":
        raise RuntimeError("This reader is verified against anomalib==2.7.0")
    from anomalib.data.datamodules.base.image import AnomalibDataModule
    from anomalib.data.datasets.image.tabular import TabularDataset
    from torchvision.transforms.v2 import Resize

    root = root.resolve()
    rows = package_rows(root)
    # Anomalib's automatic label inference does not cover normal VAL rows.
    # Supply both columns explicitly and keep package-only metadata separate.
    samples = [{
        "image_path": str((root / row["image_path"]).resolve()), "split": row["split"],
        "label_index": int(row["label_index"]),
        "label": "abnormal" if int(row["label_index"]) else "normal",
        "mask_path": "",
    } for row in rows]

    class FrozenAnomalyDataModule(AnomalibDataModule):
        def __init__(self):
            super().__init__(
                train_batch_size=batch_size, eval_batch_size=batch_size,
                num_workers=0, augmentations=Resize((image_size, image_size)),
                test_split_mode="none", val_split_mode="from_dir",
            )

        def _setup(self, _stage=None):
            for split in ("train", "val", "test"):
                setattr(self, f"{split}_data", TabularDataset(
                    # package_rows already checked confinement and all hashes.
                    # Avoid upstream ASCII-only path validation for Unicode roots.
                    name="dataset_manager", samples=samples, root=None, split=split,
                ))

        def _create_test_split(self):
            # Explicit immutable sets: the base class must not sample train.
            return

        def _create_val_split(self):
            # Val is supplied separately, never drawn from the held-out test.
            return

    return FrozenAnomalyDataModule()


def check_reader(root: Path) -> dict:
    rows = package_rows(root)
    module = create_datamodule(root)
    for stage in ("fit", "test"):
        module.setup(stage)
        for split in ("train", "val", "test"):
            actual = getattr(module, f"{split}_data").samples
            expected = {(root / r["image_path"]).resolve().as_posix() for r in rows if r["split"] == split}
            found = {Path(p).resolve().as_posix() for p in actual.image_path}
            if expected != found:
                raise AssertionError(f"Loader changed the {split} sample set")
            actual_labels = {Path(p).resolve().as_posix(): int(label) for p, label in zip(actual.image_path, actual.label_index, strict=True)}
            expected_labels = {(root / r["image_path"]).resolve().as_posix(): int(r["label_index"]) for r in rows if r["split"] == split}
            if actual_labels != expected_labels:
                raise AssertionError("Loader changed labels")
    counts = {}
    for split in ("train", "val", "test"):
        observed = {}
        for batch in getattr(module, f"{split}_dataloader")():
            for path, label in zip(batch.image_path, batch.gt_label.tolist(), strict=True):
                key = Path(path).resolve().as_posix()
                if key in observed:
                    raise AssertionError("Loader repeated an image")
                observed[key] = int(label)
        expected = {(root / r["image_path"]).resolve().as_posix(): int(r["label_index"]) for r in rows if r["split"] == split}
        if observed != expected:
            raise AssertionError(f"Batches changed the {split} sample set or labels")
        counts[split] = len(observed)
    return {"anomalib": version("anomalib"), "samples": counts, "split_preserved": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--check-only", action="store_true", help="Verify files without importing the training framework")
    args = parser.parse_args()
    result = {"verified_samples": len(package_rows(args.root))} if args.check_only else check_reader(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
