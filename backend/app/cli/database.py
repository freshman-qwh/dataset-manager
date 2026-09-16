from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.migrations import (
    create_verified_backup,
    migration_status,
    upgrade_database,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or upgrade a Dataset Manager SQLite database."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser(
        "status",
        help="Show the current and target schema revisions.",
    )
    status_parser.add_argument("--database", required=True, type=Path)

    backup_parser = subparsers.add_parser(
        "backup",
        help="Create and verify an online SQLite backup without modifying the source.",
    )
    backup_parser.add_argument("--database", required=True, type=Path)
    backup_parser.add_argument("--backup-dir", type=Path)

    upgrade_parser = subparsers.add_parser(
        "upgrade",
        help="Back up and atomically upgrade an offline database.",
    )
    upgrade_parser.add_argument("--database", required=True, type=Path)
    upgrade_parser.add_argument("--backup-dir", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "status":
        result = migration_status(args.database).to_dict()
    elif args.command == "backup":
        result = create_verified_backup(args.database, args.backup_dir).to_dict()
    else:
        result = upgrade_database(args.database, args.backup_dir).to_dict()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
