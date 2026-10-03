"""Dataset inventory and local LanceDB regression tests; no network needed."""
from dataclasses import replace
from datetime import datetime, timezone
from importlib.util import find_spec
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared_data import inventory
from shared_data.core import JSON_SCHEMA, json_records, query_record
from shared_data.tables import LanceTables
from shared_data.__main__ import main


class SharedDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "data"
        self.root.mkdir()
        self.price_schema = pa.schema([
            ("Date", pa.timestamp("ns", tz="UTC")),
            ("ticker", pa.string()), ("Close", pa.float64()),
        ])
        prices = pa.Table.from_pylist([
            {"Date": datetime(2024, 1, 2, tzinfo=timezone.utc), "ticker": "AAA", "Close": 12.5},
            {"Date": datetime(2024, 1, 3, tzinfo=timezone.utc), "ticker": "AAA", "Close": None},
        ], schema=self.price_schema)
        self.write_parquet("raw/historical_prices.parquet", prices)
        self.write_parquet("processed/features.parquet", prices)
        self.write("asset_universe.csv", "ticker\nAAA\n")
        record = {"document_id": "news:provider:1:v1", "source_type": "news",
                  "provider_id": "1", "tickers": ["AAA"], "text": "Original text",
                  "published_at": "2024-01-01T10:00:00Z",
                  "available_at": "2024-01-02T10:00:00Z", "custom": {"nullable": None}}
        self.write("artifacts/news/documents.jsonl", json.dumps(record) + "\n")
        sec = dict(record, document_id="sec:1:v1", source_type="sec", normalization_version=1)
        self.write("artifacts/sec/documents.jsonl", json.dumps(sec) + "\n")
        self.write("artifacts/sec/raw/filing.html", "<html>Original filing</html>")
        self.write("artifacts/sec/coverage.json", '{"AAA": "complete"}')
        self.write("artifacts/prepared/manifest.json", '{"version": 1}')

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def write_parquet(self, relative, table):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path)

    def test_query_rows_preserve_publication_availability_and_full_payload(self):
        path = self.root / "artifacts/news/documents.jsonl"
        original = list(json_records(path))[0]
        table = pa.Table.from_pylist([query_record(original)], schema=JSON_SCHEMA)
        row = table.to_pylist()[0]
        self.assertEqual(row["published_at"], datetime(2024, 1, 1, 10, tzinfo=timezone.utc))
        self.assertEqual(row["available_at"], datetime(2024, 1, 2, 10, tzinfo=timezone.utc))
        self.assertEqual(row["tickers"], ["AAA"])
        self.assertEqual(json.loads(row["payload_json"]), original)
        self.assertIsNone(row["updated_at"])

    def test_query_timestamp_without_timezone_is_rejected(self):
        self.write("artifacts/news/documents.jsonl", json.dumps({"published_at": "2024-01-01T10:00:00"}) + "\n")
        with self.assertRaises(ValueError):
            inventory(self.root)

    def test_inventory_excludes_secrets_caches_and_symlinks(self):
        for path in ("raw/.env", "raw/__pycache__/bad.pyc", "artifacts/news/quota.sqlite", "raw/secret.pem"):
            self.write(path, "private")
        self.write("artifacts/prepared/sentiment_cache.json", '{"cache": true}')
        (self.root / "raw/link.csv").symlink_to(self.root / "asset_universe.csv")
        paths = {entry.path for entry in inventory(self.root).files}
        for excluded in ("raw/.env", "raw/__pycache__/bad.pyc", "artifacts/news/quota.sqlite", "raw/secret.pem", "raw/link.csv"):
            self.assertNotIn(excluded, paths)

    def test_extra_manual_raw_inputs_are_deduplicated_only_when_identical(self):
        extra = Path(self.temp.name) / "other-raw"
        manual = extra / "manual_macro" / "fred.csv"
        manual.parent.mkdir(parents=True)
        manual.write_text("DATE,VALUE\n2024-01-01,4\n")
        inv = inventory(self.root, extra_raw_root=extra)
        self.assertIn("raw/manual_macro/fred.csv", {entry.path for entry in inv.files})
        self.write("raw/manual_macro/fred.csv", manual.read_text())
        paths = [entry.path for entry in inventory(self.root, extra_raw_root=extra).files]
        self.assertEqual(paths.count("raw/manual_macro/fred.csv"), 1)
        manual.write_text("DATE,VALUE\n2024-01-01,5\n")
        with self.assertRaises(ValueError):
            inventory(self.root, extra_raw_root=extra)

    @unittest.skipUnless(find_spec("lancedb"), "Optional LanceDB SDK is not installed")
    def test_lancedb_sdk_builds_queries_and_verifies_real_tables(self):
        import lancedb

        self.write("artifacts/prepared/chunks.jsonl", "")
        inv = inventory(self.root)
        entries = {entry.path: entry for entry in inv.files}
        database = Path(self.temp.name) / "lancedb"
        adapter = LanceTables(lambda prefix: lancedb.connect(database / prefix))
        for spec in inv.tables:
            adapter.build("snapshot", spec, entries[spec.file_path].local_path)
            adapter.verify("snapshot", spec)
        connection = lancedb.connect(database / "snapshot")
        prices = connection.open_table("historical_prices")
        actual_prices = prices.search().where("ticker = 'AAA'").to_arrow()
        self.assertEqual(actual_prices.schema, self.price_schema)
        rows = sorted(actual_prices.to_pylist(), key=lambda item: item["Date"])
        self.assertEqual([item["Close"] for item in rows], [12.5, None])
        self.assertEqual(rows[0]["Date"], datetime(2024, 1, 2, tzinfo=timezone.utc))
        news = connection.open_table("news_documents").search().where("provider_id = '1'").to_arrow().to_pylist()[0]
        self.assertEqual(news["published_at"], datetime(2024, 1, 1, 10, tzinfo=timezone.utc))
        self.assertEqual(news["available_at"], datetime(2024, 1, 2, 10, tzinfo=timezone.utc))
        self.assertEqual(json.loads(news["payload_json"]), list(json_records(self.root / "artifacts/news/documents.jsonl"))[0])
        self.assertEqual(connection.open_table("prepared_chunks").count_rows(), 0)
        spec = next(item for item in inv.tables if item.name == "historical_prices")
        with self.assertRaises(ValueError):
            adapter.verify("snapshot", replace(spec, rows=3))

    def test_inventory_cli_preserves_schemas_and_does_not_change_sources(self):
        before = {path.relative_to(self.root): path.read_bytes()
                  for path in self.root.rglob("*") if path.is_file()}
        output = StringIO()
        with patch("sys.stdout", output):
            self.assertEqual(main(["inventory", "--source-root", str(self.root)]), 0)
        manifest = json.loads(output.getvalue())
        tables = {table["name"]: table for table in manifest["tables"]}
        self.assertEqual(tables["historical_prices"]["schema"], str(self.price_schema))
        self.assertEqual(tables["historical_prices"]["rows"], 2)
        self.assertIn("news_documents", tables)
        self.assertIn("sec_documents", tables)
        self.assertTrue(any(item["path"] == "artifacts/sec/raw/filing.html"
                            for item in manifest["files"]))
        self.assertEqual(manifest["total_bytes"], sum(len(value) for value in before.values()))
        after = {path.relative_to(self.root): path.read_bytes()
                 for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_inventory_cli_sanitizes_invalid_record_errors(self):
        self.write("artifacts/news/documents.jsonl", "private malformed record")
        errors = StringIO()
        with patch("sys.stderr", errors):
            self.assertEqual(main(["inventory", "--source-root", str(self.root)]), 1)
        self.assertNotIn("private malformed record", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
