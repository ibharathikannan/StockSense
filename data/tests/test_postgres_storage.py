"""Real PostgreSQL migration regressions against an explicitly configured local target.

Set STOCKSENSE_TEST_POSTGRES_DSN only for a disposable local PostgreSQL server.
No application or Azure connection settings are read by this suite.
"""
from datetime import date, datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared_data import inventory
from shared_data.core import SharedDataError


@pytest.fixture
def pg():
    dsn = os.environ.get("STOCKSENSE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("STOCKSENSE_TEST_POSTGRES_DSN is not configured")
    psycopg = pytest.importorskip("psycopg")
    parameters = psycopg.conninfo.conninfo_to_dict(dsn)
    host = parameters.get("host", "")
    if host not in {"localhost", "127.0.0.1", "::1"} and not host.startswith("/"):
        pytest.fail("PostgreSQL migration tests require an explicit local disposable host")
    from shared_data import postgres
    with psycopg.connect(dsn, autocommit=True) as connection:
        created = []
        yield connection, postgres, created
        for inv in created:
            snapshot_id, schema = postgres.snapshot_identity(inv)
            connection.execute(psycopg.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                psycopg.sql.Identifier(schema)))
            if connection.execute("SELECT to_regclass('stocksense_storage.snapshots')").fetchone()[0]:
                connection.execute("DELETE FROM stocksense_storage.snapshot_files WHERE snapshot_id=%s", (snapshot_id,))
                connection.execute("DELETE FROM stocksense_storage.datasets WHERE snapshot_id=%s", (snapshot_id,))
                connection.execute("DELETE FROM stocksense_storage.snapshots WHERE snapshot_id=%s", (snapshot_id,))
        if connection.execute("SELECT to_regclass('stocksense_storage.file_blobs')").fetchone()[0]:
            connection.execute("DELETE FROM stocksense_storage.file_blobs b WHERE sha256=ANY(%s) AND NOT EXISTS "
                               "(SELECT 1 FROM stocksense_storage.snapshot_files f WHERE f.sha256=b.sha256)",
                               ([entry.sha256 for inv in created for entry in inv.files],))


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    def write(relative, text):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    def parquet(relative, rows, schema):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    parquet("raw/historical_prices.parquet", [
        {"Date": datetime(2024, 1, 2, tzinfo=timezone.utc), "ticker": "AAA", "Adj Close": 12.5, "Volume": 12345678901},
        {"Date": datetime(2024, 1, 3, tzinfo=timezone.utc), "ticker": "AAA", "Adj Close": None, "Volume": None},
    ], pa.schema([("Date", pa.timestamp("ns", tz="UTC")), ("ticker", pa.string()),
                  ("Adj Close", pa.float64()), ("Volume", pa.int64())]))
    parquet("raw/macro_indicators.parquet", [
        {"date": date(2024, 1, 1), "value": None, "available": False},
        {"date": date(2024, 1, 2), "value": 4.25, "available": True},
    ], pa.schema([("date", pa.date32()), ("value", pa.float64()), ("available", pa.bool_())]))
    write("asset_universe.csv", 'ticker,forecast_eligible,label\nAAA,false,"quote "" and backslash \\"\n')
    base = {"document_id": "news:1:v1", "source_type": "news", "provider_id": "1",
            "tickers": ["AAA", "B'BB"], "published_at": "2024-01-01T10:00:00Z",
            "available_at": "2024-01-02T10:00:00Z", "text": 'quote " slash \\ newline\nUnicode café',
            "provider_sentiment": None, "extra": {"nested": [None, 0, False]}}
    records = [base, dict(base, document_id="news:1:v2", text="Revision", updated_at="2024-01-03T00:00:00Z")]
    write("artifacts/news/documents.jsonl", "\n".join(json.dumps(row) for row in records) + "\n")
    write("artifacts/prepared/chunks.jsonl", json.dumps(dict(base, chunk_id="chunk-1", document_id="news:1:v1", char_start=0, char_end=42)) + "\n")
    write("artifacts/prepared/sentiment.jsonl", json.dumps({"document_id": "news:1:v1", "ticker": "AAA", "status": "unavailable", "score": None}) + "\n")
    write("artifacts/sec/raw/filing.html", '<html>quote " café\n</html>')
    return root, records


def tracked(pg, root):
    inv = inventory(root)
    pg[2].append(inv)
    return inv


def query_table(connection, schema, table, fields="*"):
    from psycopg import sql
    return connection.execute(sql.SQL("SELECT " + fields + " FROM {}.{} ORDER BY _source_row").format(
        sql.Identifier(schema), sql.Identifier(table))).fetchall()


def test_import_preserves_numeric_text_revisions_and_archive(pg, source):
    connection, postgres, _ = pg
    root, records = source
    inv = tracked(pg, root)
    result = postgres.import_snapshot(connection, inv)
    schema = result["schema"]
    assert result["archive_complete"] is True
    assert result["archived_files"] == len(inv.files)
    assert query_table(connection, schema, "historical_prices", '"Date",ticker,"Adj Close","Volume"') == [
        (datetime(2024, 1, 2, tzinfo=timezone.utc), "AAA", 12.5, 12345678901),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), "AAA", None, None),
    ]
    assert query_table(connection, schema, "macro_indicators", 'date,value,available') == [
        (date(2024, 1, 1), None, False), (date(2024, 1, 2), 4.25, True)]
    rows = query_table(connection, schema, "news_documents", "document_id,text,tickers,updated_at,payload")
    assert [row[4] for row in rows] == records
    assert rows[0][1] == records[0]["text"]
    assert rows[0][2] == records[0]["tickers"]
    assert rows[0][3] is None
    assert rows[1][3] == datetime(2024, 1, 3, tzinfo=timezone.utc)
    sentiment = query_table(connection, schema, "prepared_sentiment", "payload,published_at")
    assert sentiment[0][0]["score"] is None
    assert sentiment[0][1] is None
    assert query_table(connection, schema, "asset_universe", "forecast_eligible")[0][0] == "false"
    blobs = connection.execute("SELECT f.path,b.sha256,b.original_size,b.gzip_bytes "
                               "FROM stocksense_storage.snapshot_files f JOIN stocksense_storage.file_blobs b "
                               "ON f.sha256=b.sha256 WHERE f.snapshot_id=%s", (result["snapshot_id"],)).fetchall()
    entries = {entry.path: entry for entry in inv.files}
    for path, digest, size, compressed in blobs:
        original = gzip.decompress(compressed)
        assert original == entries[path].local_path.read_bytes()
        assert len(original) == size
        assert hashlib.sha256(original).hexdigest() == digest
    assert postgres.verify_snapshot(connection, inv)["archive_complete"] is True
    assert postgres.import_snapshot(connection, inv) == result
    assert connection.execute("SELECT count(*) FROM stocksense_storage.snapshot_files WHERE snapshot_id=%s",
                              (result["snapshot_id"],)).fetchone()[0] == len(inv.files)


def test_identity_ignores_local_directory_and_changed_files_keep_old_snapshot(pg, source, tmp_path):
    connection, postgres, _ = pg
    root, _ = source
    first = tracked(pg, root)
    moved = tmp_path / "copy"
    shutil.copytree(root, moved)
    assert postgres.snapshot_identity(inventory(moved)) == postgres.snapshot_identity(first)
    old = postgres.import_snapshot(connection, first, archive=False)
    path = root / "artifacts/news/documents.jsonl"
    path.write_text(path.read_text() + json.dumps({"document_id": "news:2:v1", "text": "new"}) + "\n")
    second = tracked(pg, root)
    new = postgres.import_snapshot(connection, second, archive=False)
    assert old["snapshot_id"] != new["snapshot_id"]
    assert len(query_table(connection, old["schema"], "news_documents")) == 2
    assert len(query_table(connection, new["schema"], "news_documents")) == 3
    assert new["archive_complete"] is False
    assert new["archived_files"] == 0


def test_interrupted_dataset_copy_rolls_back_and_resumes(pg, source, monkeypatch):
    connection, postgres, _ = pg
    inv = tracked(pg, source[0])
    original = postgres.rows_for
    def interrupted(path):
        for number, row in enumerate(original(path)):
            if path.name == "macro_indicators.parquet" and number == 1:
                raise RuntimeError("simulated interruption")
            yield row
    with monkeypatch.context() as context:
        context.setattr(postgres, "rows_for", interrupted)
        with pytest.raises((RuntimeError, SharedDataError)):
            postgres.import_snapshot(connection, inv, archive=False)
    snapshot_id, schema = postgres.snapshot_identity(inv)
    assert len(query_table(connection, schema, "historical_prices")) == 2
    assert connection.execute("SELECT count(*) FROM stocksense_storage.datasets "
                              "WHERE snapshot_id=%s AND table_name='macro_indicators'", (snapshot_id,)).fetchone()[0] == 0
    assert connection.execute("SELECT to_regclass(%s)", (schema + ".macro_indicators",)).fetchone()[0] is None
    postgres.import_snapshot(connection, inv)
    assert postgres.verify_snapshot(connection, inv)["archive_complete"] is True


def test_archive_verification_does_not_depend_on_database_collation(pg, source):
    connection, postgres, _ = pg
    collation = connection.execute("SELECT collname FROM pg_collation "
                                   "WHERE collname IN ('en_US.UTF-8','en_US.utf8','en-US-x-icu') LIMIT 1").fetchone()
    if collation is None:
        pytest.skip("No English locale collation installed on this local test server")
    root, _ = source
    (root / "artifacts/prepared/sentiment_aggregates.json").write_text('{}')
    inv = tracked(pg, root)
    result = postgres.import_snapshot(connection, inv)
    from psycopg import sql
    with connection.transaction(force_rollback=True):
        connection.execute(sql.SQL('ALTER TABLE stocksense_storage.snapshot_files '
                                   'ALTER COLUMN path TYPE text COLLATE {}').format(
                                       sql.Identifier(collation[0])))
        ordered = connection.execute('SELECT path,sha256 FROM stocksense_storage.snapshot_files '
                                     'WHERE snapshot_id=%s ORDER BY path', (result['snapshot_id'],)).fetchall()
        assert ordered != sorted(ordered)
        assert postgres.verify_snapshot(connection, inv)["archive_complete"] is True


@pytest.mark.parametrize("damage", ["row", "schema", "archive"])
def test_verification_detects_corruption(pg, source, damage):
    from psycopg import sql
    connection, postgres, _ = pg
    inv = tracked(pg, source[0])
    result = postgres.import_snapshot(connection, inv)
    target = sql.SQL("{}.historical_prices").format(sql.Identifier(result["schema"]))
    if damage == "row":
        connection.execute(sql.SQL('UPDATE {} SET "Adj Close"=999 WHERE _source_row=(SELECT min(_source_row) FROM {})').format(target, target))
    elif damage == "schema":
        connection.execute(sql.SQL('ALTER TABLE {} DROP COLUMN "Volume"').format(target))
    else:
        connection.execute("UPDATE stocksense_storage.file_blobs SET gzip_bytes=%s WHERE sha256=%s",
                           (b"invalid gzip", inv.files[0].sha256))
    with pytest.raises(SharedDataError):
        postgres.verify_snapshot(connection, inv)


def test_unsupported_arrow_type_fails_without_completed_snapshot(pg, tmp_path):
    connection, postgres, _ = pg
    root = tmp_path / "unsupported"
    (root / "raw").mkdir(parents=True)
    pq.write_table(pa.table({"nested": [[1, 2]]}), root / "raw/historical_prices.parquet")
    inv = tracked(pg, root)
    with pytest.raises(SharedDataError, match="unsupported Arrow type"):
        postgres.import_snapshot(connection, inv)
