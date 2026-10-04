"""Download the original Meta SAM ViT-B checkpoint, verifying bytes before install."""

import argparse
import hashlib
import os
import sys
from pathlib import Path
import urllib.request

URL = "https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth"
SHA256 = "ec2df62732614e57411cdcf32a23ffdf28910380d03139ee0f4fcbe91eb8c912"
SIZE = 375042383


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def download(target: Path) -> None:
    if target.exists():
        if target.stat().st_size == SIZE and digest(target) == SHA256:
            print(f"Verified existing SAM ViT-B: {target}")
            return
        raise SystemExit(f"Existing file failed verification; move it aside before retrying: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    total = 0
    checksum = hashlib.sha256()
    with urllib.request.urlopen(URL, timeout=60) as response, partial.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            checksum.update(chunk)
            total += len(chunk)
            if total % (32 * 1024 * 1024) == 0:
                print(f"Downloaded {total // (1024 * 1024)} / 358 MiB", flush=True)
    if total != SIZE or checksum.hexdigest() != SHA256:
        raise SystemExit(f"Download verification failed; incomplete file retained at {partial}")
    partial.replace(target)
    print(f"Verified SAM ViT-B: {target}\nSHA256: {SHA256}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.core.config import get_settings

    default = get_settings().storage_root / "models" / "sam" / "sam_vit_b_01ec64.pth"
    parser.add_argument("--output", type=Path, default=Path(os.getenv("SAM_CHECKPOINT", str(default))))
    args = parser.parse_args()
    download(args.output.expanduser().resolve())
