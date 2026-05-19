from pathlib import Path
import struct


def read_image_size(path: Path) -> tuple[int, int] | None:
    """Return image width and height for common formats without decoding pixels."""
    try:
        with path.open("rb") as file:
            header = file.read(32)
            if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
                width, height = struct.unpack(">II", header[16:24])
                return int(width), int(height)
            if header[:6] in (b"GIF87a", b"GIF89a") and len(header) >= 10:
                width, height = struct.unpack("<HH", header[6:10])
                return int(width), int(height)
            if header.startswith(b"BM") and len(header) >= 26:
                width, height = struct.unpack("<II", header[18:26])
                return int(width), int(height)
            if header.startswith(b"\xff\xd8"):
                return _read_jpeg_size(file)
    except OSError:
        return None
    except (struct.error, ValueError):
        return None
    return None


def _read_jpeg_size(file) -> tuple[int, int] | None:
    file.seek(2)
    while True:
        marker_start = file.read(1)
        if not marker_start:
            return None
        if marker_start != b"\xff":
            continue
        marker = file.read(1)
        while marker == b"\xff":
            marker = file.read(1)
        if marker in {b"\xd8", b"\xd9"}:
            continue
        length_raw = file.read(2)
        if len(length_raw) != 2:
            return None
        length = struct.unpack(">H", length_raw)[0]
        if length < 2:
            return None
        if marker in {
            b"\xc0",
            b"\xc1",
            b"\xc2",
            b"\xc3",
            b"\xc5",
            b"\xc6",
            b"\xc7",
            b"\xc9",
            b"\xca",
            b"\xcb",
            b"\xcd",
            b"\xce",
            b"\xcf",
        }:
            payload = file.read(5)
            if len(payload) != 5:
                return None
            height, width = struct.unpack(">HH", payload[1:5])
            return int(width), int(height)
        file.seek(length - 2, 1)
