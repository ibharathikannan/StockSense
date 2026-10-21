"""Enable the pgvector extension on the shared-data PostgreSQL database.

Run once before building embeddings (P3). pgvector is enabled at the database level, so
this touches no schema or table. Point PGDATABASE at the shared-data database
(stocksense_data), not the application database.

    python -m data.rag.enable_pgvector --env-file data/.env --prompt-password

Connection settings come from libpq PG* variables (PGHOST, PGDATABASE, PGUSER,
PGSSLMODE=require, ...), loaded from the environment or the optional env file exactly like
the shared-data migration. Secrets are never printed.

On Azure Database for PostgreSQL the `vector` extension must also be allow-listed on the
server (the `azure.extensions` server parameter) before CREATE EXTENSION can succeed; this
script reports that clearly if it is blocked rather than leaking driver internals.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys


def _fail(message: str) -> SystemExit:
    print(message, file=sys.stderr)
    return SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enable pgvector on the shared-data database.")
    parser.add_argument("--env-file", default=None, help="Optional env file (default: data/.env).")
    parser.add_argument(
        "--prompt-password",
        action="store_true",
        help="Prompt for the password instead of reading PGPASSWORD / .pgpass.",
    )
    args = parser.parse_args(argv)

    try:
        from data.collection_common import load_environment
    except ImportError:  # running as a module from inside data/
        from collection_common import load_environment
    load_environment(args.env_file)

    missing = [name for name in ("PGHOST", "PGDATABASE", "PGUSER") if not os.environ.get(name)]
    if missing:
        raise _fail("Configure " + ", ".join(missing) + " in the environment or data/.env")

    import psycopg

    settings: dict[str, object] = {
        "autocommit": True,
        "connect_timeout": os.environ.get("PGCONNECT_TIMEOUT", "15"),
        "sslmode": os.environ.get("PGSSLMODE", "require"),
    }
    if args.prompt_password:
        settings["password"] = getpass.getpass("PostgreSQL password: ")

    try:
        with psycopg.connect(**settings) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            row = conn.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
    except psycopg.Error:
        # Driver errors can echo credentials or connection strings; never print them.
        raise _fail(
            "Enabling pgvector failed. On Azure Database for PostgreSQL, add 'vector' to "
            "the azure.extensions server parameter (and restart), then re-run. Otherwise "
            "check connection settings and that the role may CREATE EXTENSION."
        )

    database = os.environ.get("PGDATABASE")
    if not row:
        raise _fail("CREATE EXTENSION ran but pgvector is not present; check server permissions.")
    print(f"pgvector {row[0]} is enabled on database '{database}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
