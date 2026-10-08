"""Read numerical forecasting inputs without mutating datasets or snapshots."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

import pandas as pd


class SourceError(ValueError):
    """A forecasting source is absent or cannot be verified."""


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_local(feature_path: Path, price_path: Path, universe_path: Path):
    frames, datasets = [], {}
    for name, selected in zip(
        ("price_only_features", "historical_prices", "asset_universe"),
        (feature_path, price_path, universe_path),
    ):
        path = Path(selected).resolve()
        if not path.is_file():
            raise SourceError(f"Missing local {name} input: {path}")
        before = _hash(path)
        frame = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
        if _hash(path) != before:
            raise SourceError(f"Local input changed while reading: {name}")
        frames.append(frame)
        datasets[name] = {"path": str(path), "sha256": before,
                          "rows": len(frame), "columns": list(frame.columns)}
    return (*frames, {"source": "local", "datasets": datasets})


def _read_snapshot(conn, schema: str):
    # Schema was validated before opening a connection. Table names are constants.
    snapshot = conn.execute(
        "SELECT snapshot_id, schema_name, status FROM stocksense_storage.snapshots "
        "WHERE schema_name=%s", (schema,),
    ).fetchone()
    if not snapshot or snapshot[1] != schema or snapshot[2] != "complete":
        raise SourceError("Requested snapshot is absent or not complete; no fallback used")
    identity = snapshot[0]
    if not re.fullmatch(r"[0-9a-f]{64}", identity) or schema != "ss_" + identity[:20]:
        raise SourceError("Snapshot identity does not match the pinned schema")
    frames, datasets = [], {}
    for table in ("price_only_features", "historical_prices", "asset_universe"):
        metadata = conn.execute(
            "SELECT file_hash, row_count, columns_json FROM stocksense_storage.datasets "
            "WHERE snapshot_id=%s AND table_name=%s", (identity, table),
        ).fetchone()
        if not metadata:
            raise SourceError(f"Required snapshot dataset metadata absent: {table}")
        digest, expected_rows, payload = metadata
        columns = json.loads(payload) if isinstance(payload, str) else payload
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SourceError(f"Invalid dataset hash: {table}")
        names = [column[0] for column in columns]
        if len(names) != len(set(names)) or "_source_row" in names:
            raise SourceError(f"Invalid dataset columns: {table}")
        cursor = conn.execute(f'SELECT * FROM "{schema}"."{table}" ORDER BY "_source_row"')
        actual_names = [column.name for column in cursor.description]
        if actual_names != names + ["_source_row"]:
            raise SourceError(f"Snapshot column mismatch: {table}")
        frame = pd.DataFrame.from_records(cursor.fetchall(), columns=actual_names)
        if len(frame) != expected_rows or frame["_source_row"].tolist() != list(range(1, expected_rows + 1)):
            raise SourceError(f"Snapshot row count or source ordering mismatch: {table}")
        frames.append(frame.drop(columns="_source_row"))
        datasets[table] = {"sha256": digest, "rows": expected_rows, "columns": names}
    return (*frames, {"source": "postgres", "snapshot_id": identity,
                      "schema": schema, "datasets": datasets})


def load_postgres(schema: str, *, env_file: Path | None = None):
    if not re.fullmatch(r"ss_[0-9a-f]{20}", schema):
        raise SourceError("Use an explicit immutable snapshot schema: ss_ followed by 20 lowercase hex digits")
    try:
        import psycopg
    except ImportError:
        raise SourceError("PostgreSQL source requires optional psycopg: install data/requirements-postgres.txt") from None
    try:
        from ..collection_common import load_environment
    except ImportError:
        from collection_common import load_environment
    if env_file is not None:
        load_environment(env_file)
    missing = [key for key in ("PGHOST", "PGDATABASE", "PGUSER") if not os.environ.get(key)]
    if missing:
        raise SourceError("Configure " + ", ".join(missing) + " using libpq environment settings")
    try:
        with psycopg.connect(
            autocommit=False, connect_timeout=os.environ.get("PGCONNECT_TIMEOUT", "15"),
            sslmode=os.environ.get("PGSSLMODE", "require"),
            options="-c default_transaction_read_only=on",
        ) as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            return _read_snapshot(conn, schema)
    except psycopg.Error:
        raise SourceError("PostgreSQL source read failed; check connection permissions and required snapshot tables") from None
