import csv
import hashlib
from pathlib import Path

import pytest
from PIL import Image

from app.templates.anomaly_reader import package_rows


def test_reader_checks_actual_bytes_and_split_isolation(tmp_path: Path) -> None:
    rows = []
    for index, (split, label) in enumerate([("train", 0), ("val", 0), ("val", 1), ("test", 0), ("test", 1)]):
        path = tmp_path / f"{index}.png"
        Image.new("RGB", (8, 8), (index * 20, 0, 0)).save(path)
        rows.append(dict(sample_id=index, image_path=path.name, label_index=label, split=split,
                         group_id=str(index), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))

    def write():
        with (tmp_path / "samples.csv").open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=rows[0])
            writer.writeheader()
            writer.writerows(rows)

    write()
    assert len(package_rows(tmp_path)) == 5
    rows[-1]["group_id"] = rows[0]["group_id"]
    write()
    with pytest.raises(ValueError, match="crosses splits"):
        package_rows(tmp_path)
    rows[-1]["group_id"] = "4"
    write()
    (tmp_path / "4.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        package_rows(tmp_path)
