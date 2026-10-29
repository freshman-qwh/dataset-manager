"""Read-only pixel decoding checks; dimensions alone do not prove usability."""

from pathlib import Path

from PIL import Image


def image_is_decodable(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image.load()
            return image.width > 0 and image.height > 0
    except (OSError, ValueError, Image.DecompressionBombError):
        return False
