"""Inspect local datasets or migrate and verify immutable PostgreSQL snapshots."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys

from .core import SharedDataError, inventory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    item = sub.add_parser("inventory")
    item.add_argument("--source-root", type=Path, default=Path("data"))
    item.add_argument("--extra-raw-root", type=Path)
    for command in ("postgres-import", "postgres-verify"):
        item = sub.add_parser(command)
        item.add_argument("--source-root", type=Path, default=Path("data"))
        item.add_argument("--extra-raw-root", type=Path)
        item.add_argument("--env-file", type=Path, default=Path("data/.env"))
        item.add_argument("--prompt-password", action="store_true")
        if command == "postgres-import":
            item.add_argument("--skip-archive", action="store_true",
                              help="Import tables only; original files remain local")
    args = parser.parse_args(argv)
    try:
        if args.command != "inventory":
            return _postgres(args)
        inv = inventory(args.source_root, args.extra_raw_root)
        result = inv.manifest()
        result["total_bytes"] = sum(file.size for file in inv.files)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except SharedDataError as error:
        print(f"Shared data: {error}", file=sys.stderr)
    except (ValueError, OSError):
        print("Shared data: Invalid or changing source datasets; inspect the selected data roots.", file=sys.stderr)
    return 1


def _postgres(args):
    # Keep the optional database driver out of read-only inventory imports.
    try:
        import psycopg
        from .postgres import import_snapshot, verify_snapshot
    except ImportError:
        raise SharedDataError("Install optional migration dependencies: "
                              "python -m pip install -r data/requirements-postgres.txt") from None
    try:
        from ..collection_common import load_environment
    except ImportError:
        from collection_common import load_environment
    load_environment(args.env_file)
    missing = [name for name in ("PGHOST", "PGDATABASE", "PGUSER") if not os.environ.get(name)]
    if missing:
        raise SharedDataError("Configure " + ", ".join(missing) + " in the environment or data/.env")
    inv = inventory(args.source_root, args.extra_raw_root)
    settings = {"autocommit": True, "connect_timeout": os.environ.get("PGCONNECT_TIMEOUT", "15"),
                "sslmode": os.environ.get("PGSSLMODE", "require")}
    if args.prompt_password:
        settings["password"] = getpass.getpass("PostgreSQL password: ")
    try:
        with psycopg.connect(**settings) as conn:
            if args.command == "postgres-import":
                result = import_snapshot(conn, inv, archive=not args.skip_archive,
                                         progress=lambda message: print(message, file=sys.stderr, flush=True))
            else:
                result = verify_snapshot(conn, inv,
                                         progress=lambda message: print(message, file=sys.stderr, flush=True))
        print(json.dumps(result, indent=2))
        return 0
    except psycopg.Error:
        # Driver errors may contain passwords, connection strings or failed row data.
        raise SharedDataError("PostgreSQL operation failed. Check connection settings, credentials, "
                              "database permissions and source types; completed uploads can be resumed.") from None
    except KeyboardInterrupt:
        raise SharedDataError("Migration interrupted; rerun the same command to resume completed uploads") from None


if __name__ == "__main__":
    raise SystemExit(main())
