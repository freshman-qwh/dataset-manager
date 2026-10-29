import hashlib
from pathlib import Path

from PIL import Image

from app.utils.image_validation import image_is_decodable


def test_full_decode_rejects_header_only_without_changing_files(tmp_path: Path) -> None:
    valid = tmp_path / "good.png"
    Image.new("RGB", (8, 8), "white").save(valid)
    broken = tmp_path / "header-only.png"
    broken.write_bytes(valid.read_bytes()[:33])
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (valid, broken)}
    assert image_is_decodable(valid)
    assert not image_is_decodable(broken)
    assert not image_is_decodable(tmp_path / "missing.png")
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (valid, broken)}
