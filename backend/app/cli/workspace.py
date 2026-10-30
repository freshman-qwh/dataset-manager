"""Restore a verified metadata bundle into a new workspace directory."""
import argparse
import json
from pathlib import Path

from app.services.workspace_backup_service import restore_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--target-dir", required=True, type=Path)
    args = parser.parse_args()
    result = restore_bundle(args.archive, args.target_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
