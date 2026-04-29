from pathlib import Path

from app.utils.file_types import detect_file_type


def test_detect_file_type():
    assert detect_file_type(Path("image.JPG")) == "image"
    assert detect_file_type(Path("clip.mp4")) == "video"
    assert detect_file_type(Path("table.csv")) == "table"
    assert detect_file_type(Path("archive.zip")) is None
