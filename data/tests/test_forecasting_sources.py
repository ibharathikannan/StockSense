"""Read-only source verification; no database or network access."""
import hashlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forecasting.sources import SourceError, load_local, load_postgres, _read_snapshot


IDENTITY = "a" * 64
SCHEMA = "ss_" + IDENTITY[:20]


class Cursor:
    def __init__(self, rows, names=()):
        self.rows = rows
        self.description = [SimpleNamespace(name=name) for name in names]

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, status="complete", rows=1):
        self.status, self.rows, self.queries = status, rows, []

    def execute(self, query, params=None):
        self.queries.append((query, params))
        if "FROM stocksense_storage.snapshots" in query:
            return Cursor([(IDENTITY, SCHEMA, self.status)])
        if "FROM stocksense_storage.datasets" in query:
            return Cursor([("b" * 64, self.rows, [["ticker", "text"]])])
        return Cursor([("AAPL", 1)], ("ticker", "_source_row"))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class SourcesTests(unittest.TestCase):
    def test_local_hashes_and_no_write(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / f"{i}.csv" for i in range(3)]
            for path in paths:
                path.write_text("ticker,price\nAAPL,10\n")
            frames = load_local(*paths)
            self.assertEqual(frames[0].ticker.tolist(), ["AAPL"])
            metadata = frames[-1]["datasets"]["price_only_features"]
            self.assertEqual(metadata["sha256"], hashlib.sha256(paths[0].read_bytes()).hexdigest())
            self.assertEqual(len(list(Path(directory).iterdir())), 3)

    def test_missing_local_file(self):
        with self.assertRaisesRegex(SourceError, "Missing local"):
            load_local(Path("/absent"), Path("/absent"), Path("/absent"))

    def test_rejects_alias_and_injection_before_connection(self):
        for schema in ("latest", SCHEMA + '"; DROP TABLE x', "public"):
            with self.assertRaisesRegex(SourceError, "explicit immutable"):
                load_postgres(schema)

    def test_snapshot_provenance_and_source_row_removal(self):
        conn = Connection()
        features, prices, universe, provenance = _read_snapshot(conn, SCHEMA)
        self.assertEqual(provenance["snapshot_id"], IDENTITY)
        for frame in (features, prices, universe):
            self.assertEqual(list(frame.columns), ["ticker"])
        self.assertTrue(all(query.startswith("SELECT") for query, _ in conn.queries))

    def test_incomplete_or_mismatched_row_count_fail(self):
        with self.assertRaisesRegex(SourceError, "not complete"):
            _read_snapshot(Connection(status="tables_only"), SCHEMA)
        with self.assertRaisesRegex(SourceError, "row count"):
            _read_snapshot(Connection(rows=2), SCHEMA)

    def test_connection_read_only_and_safe_error(self):
        class DriverError(Exception):
            pass
        conn = Connection()
        driver = SimpleNamespace(Error=DriverError, connect=lambda **kwargs: conn)
        with patch.dict(sys.modules, {"psycopg": driver}), patch.dict(
            "os.environ", {"PGHOST": "test", "PGDATABASE": "test", "PGUSER": "test"}
        ):
            load_postgres(SCHEMA)
        self.assertEqual(conn.queries[0][0], "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        def fail(**kwargs):
            raise DriverError("password=secret")
        driver.connect = fail
        with patch.dict(sys.modules, {"psycopg": driver}), patch.dict(
            "os.environ", {"PGHOST": "test", "PGDATABASE": "test", "PGUSER": "test"}
        ):
            with self.assertRaises(SourceError) as error:
                load_postgres(SCHEMA)
            self.assertNotIn("secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
