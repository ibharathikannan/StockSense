"""Immutable PostgreSQL dataset snapshots and lossless source-file archives.

Each dataset/file commits separately. A retry reuses completed uploads, while a
changed manifest gets a different schema and cannot replace an earlier snapshot.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import tempfile
from typing import Callable

from psycopg import sql
from psycopg.types.json import Jsonb

from .core import FileEntry, Inventory, SharedDataError, TableSpec, file_hash
from .postgres_records import columns_for, comparable, rows_for

STORAGE_FORMAT_VERSION = 1
META = "stocksense_storage"


def snapshot_identity(inv: Inventory) -> tuple[str, str]:
    manifest = {"storage_format_version": STORAGE_FORMAT_VERSION, **inv.manifest()}
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    identity = hashlib.sha256(encoded.encode()).hexdigest()
    return identity, f"ss_{identity[:20]}"


def _specs(inv: Inventory) -> list[TableSpec]:
    specs = list(inv.tables)
    universe = next((f for f in inv.files if f.path == "asset_universe.csv"), None)
    if universe is not None:
        columns = columns_for(universe.local_path)
        rows = sum(1 for _ in rows_for(universe.local_path))
        specs.insert(0, TableSpec("asset_universe", universe.path, rows,
                                json.dumps([(c.name, c.sql_type) for c in columns])))
    return specs


def _unchanged(entry: FileEntry) -> None:
    if entry.local_path.stat().st_size != entry.size or file_hash(entry.local_path) != entry.sha256:
        raise SharedDataError(f"Source changed during migration: {entry.path}; create a fresh inventory")


def _metadata(conn) -> None:
    with conn.transaction():
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(META)))
        conn.execute("""CREATE TABLE IF NOT EXISTS stocksense_storage.snapshots (
            snapshot_id text PRIMARY KEY, schema_name text UNIQUE NOT NULL,
            manifest jsonb NOT NULL, archive_requested boolean NOT NULL,
            status text NOT NULL, created_at timestamptz NOT NULL DEFAULT now())""")
        conn.execute("""CREATE TABLE IF NOT EXISTS stocksense_storage.datasets (
            snapshot_id text REFERENCES stocksense_storage.snapshots(snapshot_id),
            table_name text NOT NULL, file_hash text NOT NULL, row_count bigint NOT NULL,
            columns_json jsonb NOT NULL, PRIMARY KEY(snapshot_id, table_name))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS stocksense_storage.file_blobs (
            sha256 text PRIMARY KEY, original_size bigint NOT NULL, gzip_bytes bytea NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS stocksense_storage.snapshot_files (
            snapshot_id text REFERENCES stocksense_storage.snapshots(snapshot_id),
            path text NOT NULL, sha256 text REFERENCES stocksense_storage.file_blobs(sha256),
            PRIMARY KEY(snapshot_id, path))""")


def _columns_payload(columns) -> list[list[str]]:
    return [[c.name, c.sql_type] for c in columns]


def _indexes(conn, schema: str, table: str, columns) -> None:
    names = {c.name for c in columns}
    choices = []
    if {"ticker", "Date"} <= names:
        choices.append(("ticker", "Date"))
    elif "ticker" in names:
        choices.append(("ticker",))
    for field in ("document_id", "chunk_id", "provider_id", "available_at", "series_id"):
        if field in names:
            choices.append((field,))
    for fields in choices:
        # Index names are local to the snapshot schema and deterministic.
        name = f"{table}_{'_'.join(fields)}_idx"
        conn.execute(sql.SQL("CREATE INDEX {} ON {} ({})").format(
            sql.Identifier(name), sql.Identifier(schema, table),
            sql.SQL(", ").join(map(sql.Identifier, fields))))
    if "tickers" in names:
        conn.execute(sql.SQL("CREATE INDEX {} ON {} USING gin (tickers)").format(
            sql.Identifier(f"{table}_tickers_idx"), sql.Identifier(schema, table)))


def _import_table(conn, identity, schema, spec, entry) -> bool:
    columns = columns_for(entry.local_path)
    expected = _columns_payload(columns)
    existing = conn.execute("""SELECT file_hash, row_count, columns_json
        FROM stocksense_storage.datasets WHERE snapshot_id=%s AND table_name=%s""",
        (identity, spec.name)).fetchone()
    if existing:
        if existing != (entry.sha256, spec.rows, expected):
            raise SharedDataError(f"Conflicting stored dataset metadata: {spec.name}")
        return False
    _unchanged(entry)
    with conn.transaction():
        definitions = [sql.SQL("{} {}").format(sql.Identifier(c.name), sql.SQL(c.sql_type))
                       for c in columns]
        definitions.append(sql.SQL('"_source_row" bigint PRIMARY KEY'))
        conn.execute(sql.SQL("CREATE TABLE {} ({})").format(
            sql.Identifier(schema, spec.name), sql.SQL(", ").join(definitions)))
        names = [c.name for c in columns] + ["_source_row"]
        count = 0
        with conn.cursor().copy(sql.SQL("COPY {} ({}) FROM STDIN").format(
                sql.Identifier(schema, spec.name),
                sql.SQL(", ").join(map(sql.Identifier, names)))) as copy:
            for count, row in enumerate(rows_for(entry.local_path), 1):
                copy.write_row((*row, count))
        if count != spec.rows:
            raise SharedDataError(f"Source row count changed: {spec.name}")
        _unchanged(entry)
        _indexes(conn, schema, spec.name, columns)
        conn.execute("""INSERT INTO stocksense_storage.datasets
            (snapshot_id,table_name,file_hash,row_count,columns_json) VALUES (%s,%s,%s,%s,%s)""",
            (identity, spec.name, entry.sha256, count, Jsonb(expected)))
    return True


def _archive_file(conn, identity: str, entry: FileEntry) -> bool:
    stored = conn.execute("SELECT sha256 FROM stocksense_storage.snapshot_files "
                          "WHERE snapshot_id=%s AND path=%s", (identity, entry.path)).fetchone()
    if stored:
        if stored[0] != entry.sha256:
            raise SharedDataError(f"Conflicting stored file metadata: {entry.path}")
        return False
    _unchanged(entry)
    blob = conn.execute("SELECT original_size FROM stocksense_storage.file_blobs WHERE sha256=%s",
                        (entry.sha256,)).fetchone()
    with conn.transaction():
        if blob is None:
            # Compress incrementally; only compressed bytes enter the driver at once.
            with tempfile.TemporaryFile() as temp:
                digest = hashlib.sha256()
                size = 0
                with gzip.GzipFile(fileobj=temp, mode="wb", mtime=0) as compressed:
                    with entry.local_path.open("rb") as source:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(block)
                            size += len(block)
                            compressed.write(block)
                if digest.hexdigest() != entry.sha256 or size != entry.size:
                    raise SharedDataError(f"Source changed during archive: {entry.path}")
                # bytea has a per-value limit. Reject instead of silently omitting a file.
                if temp.tell() >= 1024 * 1024 * 1024:
                    raise SharedDataError(f"Archive file exceeds PostgreSQL bytea limit: {entry.path}")
                temp.seek(0)
                conn.execute("INSERT INTO stocksense_storage.file_blobs VALUES (%s,%s,%s)",
                             (entry.sha256, entry.size, temp.read()))
        elif blob[0] != entry.size:
            raise SharedDataError(f"Conflicting archived file size: {entry.path}")
        conn.execute("INSERT INTO stocksense_storage.snapshot_files VALUES (%s,%s,%s)",
                     (identity, entry.path, entry.sha256))
    return True


def _report(conn, identity, schema, specs, archive_requested) -> dict:
    count = conn.execute("SELECT count(*) FROM stocksense_storage.snapshot_files WHERE snapshot_id=%s",
                         (identity,)).fetchone()[0]
    return {"snapshot_id": identity, "schema": schema,
            "tables": {spec.name: spec.rows for spec in specs}, "archived_files": count,
            "archive_complete": archive_requested}


def import_snapshot(conn, inv: Inventory, *, archive: bool = True,
                    progress: Callable[[str], None] | None = None) -> dict:
    if not conn.autocommit:
        raise SharedDataError("PostgreSQL migration requires an autocommit connection")
    identity, schema = snapshot_identity(inv)
    specs = _specs(inv)
    if not specs:
        raise SharedDataError("No recognized datasets to import")
    entries = {entry.path: entry for entry in inv.files}
    # Preflight all types before any writes to the target.
    for spec in specs:
        columns_for(entries[spec.file_path].local_path)
    locked = conn.execute("SELECT pg_try_advisory_lock(hashtext('stocksense_data_import'))").fetchone()[0]
    if not locked:
        raise SharedDataError("Another StockSense import is running; retry when it finishes")
    try:
        _metadata(conn)
        manifest = {"storage_format_version": STORAGE_FORMAT_VERSION, **inv.manifest()}
        with conn.transaction():
            conn.execute("""INSERT INTO stocksense_storage.snapshots
                (snapshot_id,schema_name,manifest,archive_requested,status) VALUES (%s,%s,%s,%s,'importing')
                ON CONFLICT(snapshot_id) DO UPDATE SET
                archive_requested=stocksense_storage.snapshots.archive_requested OR EXCLUDED.archive_requested,
                status='importing'""", (identity, schema, Jsonb(manifest), archive))
            saved = conn.execute("SELECT schema_name,manifest,archive_requested FROM "
                                 "stocksense_storage.snapshots WHERE snapshot_id=%s", (identity,)).fetchone()
            if saved[:2] != (schema, manifest):
                raise SharedDataError("Snapshot identity conflicts with stored metadata")
            archive_requested = saved[2]
            conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
        for spec in specs:
            loaded = _import_table(conn, identity, schema, spec, entries[spec.file_path])
            if progress:
                progress(f"{'Loaded' if loaded else 'Reused'} {spec.name} ({spec.rows:,} rows)")
        if archive_requested:
            for index, entry in enumerate(inv.files, 1):
                loaded = _archive_file(conn, identity, entry)
                if progress:
                    progress(f"{'Archived' if loaded else 'Reused archive'} {index}/{len(inv.files)}: {entry.path}")
        for entry in inv.files:
            _unchanged(entry)
        conn.execute("UPDATE stocksense_storage.snapshots SET status=%s WHERE snapshot_id=%s",
                     ("complete" if archive_requested else "tables_only", identity))
        return _report(conn, identity, schema, specs, archive_requested)
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtext('stocksense_data_import'))")


def _equal(left, right) -> bool:
    left, right = comparable(left), comparable(right)
    if isinstance(left, float) and isinstance(right, float) and math.isnan(left) and math.isnan(right):
        return True
    return left == right


def _verify_table(conn, identity, schema, spec, entry) -> None:
    columns = columns_for(entry.local_path)
    metadata = conn.execute("SELECT file_hash,row_count,columns_json FROM stocksense_storage.datasets "
                            "WHERE snapshot_id=%s AND table_name=%s", (identity, spec.name)).fetchone()
    if metadata != (entry.sha256, spec.rows, _columns_payload(columns)):
        raise SharedDataError(f"Dataset metadata verification failed: {spec.name}")
    actual = conn.execute("""SELECT a.attname, pg_catalog.format_type(a.atttypid,a.atttypmod)
        FROM pg_catalog.pg_attribute a JOIN pg_catalog.pg_class c ON a.attrelid=c.oid
        JOIN pg_catalog.pg_namespace n ON c.relnamespace=n.oid
        WHERE n.nspname=%s AND c.relname=%s AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY a.attnum""", (schema, spec.name)).fetchall()
    aliases = {"timestamp": "timestamp without time zone", "timestamptz": "timestamp with time zone"}
    expected = [(c.name, aliases.get(c.sql_type, c.sql_type)) for c in columns] + [("_source_row", "bigint")]
    if actual != expected:
        raise SharedDataError(f"Table schema verification failed: {spec.name}")
    count = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(
        sql.Identifier(schema, spec.name))).fetchone()[0]
    if count != spec.rows:
        raise SharedDataError(f"Row count verification failed: {spec.name}")
    with conn.transaction():
        with conn.cursor(name="stocksense_verify_rows", binary=True) as cursor:
            cursor.itersize = 512
            cursor.execute(sql.SQL('SELECT {} FROM {} ORDER BY "_source_row"').format(
                sql.SQL(", ").join(map(sql.Identifier, [c.name for c in columns] + ["_source_row"])),
                sql.Identifier(schema, spec.name)))
            # Iterate in itersize batches: fetchone() on a server cursor would
            # issue a network round trip for every source row.
            stored_rows = iter(cursor)
            for index, source in enumerate(rows_for(entry.local_path), 1):
                stored = next(stored_rows, None)
                if (stored is None or stored[-1] != index or len(source) != len(stored) - 1
                        or not all(_equal(a, b) for a, b in zip(source, stored[:-1]))):
                    raise SharedDataError(f"Row content verification failed: {spec.name}, row {index}")
            if next(stored_rows, None) is not None:
                raise SharedDataError(f"Extra rows found: {spec.name}")


def verify_snapshot(conn, inv: Inventory, *, progress: Callable[[str], None] | None = None) -> dict:
    """Read back every row and archived file. Does not write to the database."""
    if not conn.autocommit:
        raise SharedDataError("PostgreSQL verification requires an autocommit connection")
    identity, schema = snapshot_identity(inv)
    snapshot = conn.execute("SELECT schema_name,manifest,archive_requested,status FROM "
                            "stocksense_storage.snapshots WHERE snapshot_id=%s", (identity,)).fetchone()
    manifest = {"storage_format_version": STORAGE_FORMAT_VERSION, **inv.manifest()}
    if (not snapshot or snapshot[:2] != (schema, manifest)
            or snapshot[3] != ("complete" if snapshot[2] else "tables_only")):
        raise SharedDataError("Snapshot missing, incomplete, or has conflicting metadata; run postgres-import first")
    entries = {entry.path: entry for entry in inv.files}
    specs = _specs(inv)
    for spec in specs:
        _verify_table(conn, identity, schema, spec, entries[spec.file_path])
        if progress:
            progress(f"Verified {spec.name} ({spec.rows:,} rows)")
    if snapshot[2]:
        paths = conn.execute("SELECT path,sha256 FROM stocksense_storage.snapshot_files "
                             "WHERE snapshot_id=%s ORDER BY path", (identity,)).fetchall()
        # PostgreSQL's locale collation need not match Python's Unicode ordering.
        if sorted(paths) != sorted((entry.path, entry.sha256) for entry in inv.files):
            raise SharedDataError("Archived file inventory verification failed")
        checked = set()
        for entry in inv.files:
            if entry.sha256 in checked:
                continue
            blob = conn.execute("SELECT original_size,gzip_bytes FROM stocksense_storage.file_blobs "
                                "WHERE sha256=%s", (entry.sha256,)).fetchone()
            if blob is None or blob[0] != entry.size:
                raise SharedDataError(f"Archived file size verification failed: {entry.path}")
            digest, size = hashlib.sha256(), 0
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(blob[1]), mode="rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                        size += len(block)
            except (OSError, EOFError):
                raise SharedDataError(f"Invalid archived gzip content: {entry.path}") from None
            if digest.hexdigest() != entry.sha256 or size != entry.size:
                raise SharedDataError(f"Archived file hash verification failed: {entry.path}")
            checked.add(entry.sha256)
            if progress:
                progress(f"Verified archive {len(checked)}/{len(inv.files)}: {entry.path}")
    for entry in inv.files:
        _unchanged(entry)
    return _report(conn, identity, schema, specs, snapshot[2])
