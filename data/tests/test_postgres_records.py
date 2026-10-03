"""Local PostgreSQL conversion checks; no database or network required."""
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq
try:
    from psycopg.types.json import Jsonb
except ImportError:
    Jsonb = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared_data.core import SharedDataError
from shared_data.postgres_records import Column, columns_for, comparable, rows_for


@unittest.skipIf(Jsonb is None, "Optional PostgreSQL driver is not installed")
class PostgresRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def parquet(self, table):
        path = self.root / "prices.parquet"
        pq.write_table(table, path)
        return path

    def text(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_typed_values_keep_names_nulls_dates_and_quotes(self):
        schema = pa.schema([
            ("Date", pa.date32()), ("naive", pa.timestamp("us")),
            ("aware", pa.timestamp("ns", tz="UTC")),
            ("Close", pa.float64()), ("ratio", pa.float32()),
            ("volume", pa.int64()), ("count", pa.int32()),
            ("small", pa.int16()), ("tiny", pa.int8()),
            ("flag", pa.bool_()), ("ticker", pa.string()),
        ])
        stamp = datetime(2024, 1, 1, 12, 34, 56, 123456)
        values = {"Date": date(2024, 1, 1), "naive": stamp,
                  "aware": stamp.replace(tzinfo=timezone.utc), "Close": 12.5,
                  "ratio": None, "volume": 2**40, "count": 4, "small": 3,
                  "tiny": -1, "flag": True, "ticker": 'O\'Brien, "AAA"'}
        path = self.parquet(pa.Table.from_pylist([values, {name: None for name in schema.names}], schema=schema))
        self.assertEqual([column.sql_type for column in columns_for(path)],
                         ["date", "timestamp", "timestamptz", "double precision", "real",
                          "bigint", "integer", "smallint", "smallint", "boolean", "text"])
        self.assertEqual([column.name for column in columns_for(path)], schema.names)
        self.assertEqual(list(rows_for(path)), [tuple(values.values()), (None,) * len(schema)])

    def test_json_preserves_revisions_null_sentiment_and_outcomes(self):
        first = {"document_id": "provider:1:v1", "provider_id": 1,
                 "tickers": ["AAA"], "text": 'Quotes "and" apostrophes\nnewlines',
                 "published_at": "2024-01-01T08:00:00+08:00", "sentiment": None,
                 "outcome": "failed", "custom": {"reason": "quota", "score": None}}
        second = dict(first, document_id="provider:1:v2", text="Revised", status="success")
        path = self.text("documents.jsonl", "\n" + json.dumps(first) + "\n" + json.dumps(second) + "\n")
        columns = columns_for(path)
        self.assertEqual(columns[-1], Column("payload", "jsonb"))
        rows = [dict(zip([column.name for column in columns], row)) for row in rows_for(path)]
        self.assertEqual(rows[0]["published_at"], datetime(2024, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(rows[0]["provider_id"], "1")
        self.assertIsNone(rows[0]["available_at"])
        self.assertEqual(rows[0]["payload"].obj, first)
        self.assertEqual(rows[1]["payload"].obj, second)
        self.assertEqual(comparable(Jsonb(first)), comparable(first))
        self.assertEqual(comparable(float("nan")), comparable(float("nan")))
        literal = self.text("literal.jsonl", json.dumps({"text": r"literal \u0000"}))
        self.assertEqual(list(rows_for(literal))[0][-1].obj, {"text": r"literal \u0000"})

    def test_csv_keeps_text_and_quoted_fields(self):
        path = self.text("asset_universe.csv", 'ticker,id,description\nAAA,001,"a,b and ""quotes"""\nBBB,002,\n')
        self.assertEqual(columns_for(path), [Column(name, "text") for name in ("ticker", "id", "description")])
        self.assertEqual(list(rows_for(path)), [("AAA", "001", 'a,b and "quotes"'), ("BBB", "002", "")])

    def test_csv_rejects_bad_headers_and_lengths(self):
        for text in ("ticker,ticker\nA,B\n", "ticker,\nA,B\n", "ticker,id\nA\n", "ticker\nA,B\n"):
            with self.subTest(text=text):
                path = self.text("asset_universe.csv", text)
                with self.assertRaises(SharedDataError):
                    list(rows_for(path))

    def test_reserved_source_field_rejected(self):
        path = self.parquet(pa.table({"_source_row": [1]}))
        with self.assertRaisesRegex(SharedDataError, "reserved"):
            columns_for(path)
        path = self.text("documents.jsonl", '{"_source_row": 2}')
        with self.assertRaisesRegex(SharedDataError, "reserved"):
            list(rows_for(path))
        path = self.text("asset_universe.csv", "_source_row\n2\n")
        with self.assertRaisesRegex(SharedDataError, "reserved"):
            columns_for(path)

    def test_rejects_unsupported_types_and_lossy_values(self):
        for array in (pa.array([[1]], type=pa.list_(pa.int64())),
                      pa.array([b"a"], type=pa.binary()),
                      pa.array([None], type=pa.null())):
            with self.subTest(type=array.type):
                with self.assertRaisesRegex(SharedDataError, "unsupported"):
                    columns_for(self.parquet(pa.table({"value": array})))
        path = self.parquet(pa.table({"stamp": pa.array([1001], type=pa.timestamp("ns"))}))
        with self.assertRaisesRegex(SharedDataError, "row 1.*submicrosecond"):
            list(rows_for(path))
        path = self.parquet(pa.table({"large": pa.array([2**63], type=pa.uint64())}))
        with self.assertRaisesRegex(SharedDataError, "row 1.*bigint range"):
            list(rows_for(path))
        path = self.parquet(pa.table({"text": ["secret\x00value"]}))
        with self.assertRaisesRegex(SharedDataError, "NUL"):
            list(rows_for(path))

    def test_unsigned_values_within_range(self):
        path = self.parquet(pa.table({"small": pa.array([255], type=pa.uint8()),
                                      "medium": pa.array([65535], type=pa.uint16()),
                                      "large": pa.array([2**32 - 1], type=pa.uint32()),
                                      "largest": pa.array([2**63 - 1], type=pa.uint64())}))
        self.assertEqual([column.sql_type for column in columns_for(path)],
                         ["smallint", "integer", "bigint", "bigint"])
        self.assertEqual(list(rows_for(path)), [(255, 65535, 2**32 - 1, 2**63 - 1)])

    def test_json_failures_give_location_without_record_data(self):
        for text in ('{"text":"SECRET", "published_at":"SECRET"}',
                     '{"text":"SECRET", "score":NaN}', '["SECRET"]', '{"SECRET"',
                     '{"text":"SECRET", "nested":{"bad":"\\u0000"}}'):
            with self.subTest(text=text):
                path = self.text("documents.jsonl", "\n" + text)
                with self.assertRaises(SharedDataError) as caught:
                    list(rows_for(path))
                self.assertIn("row 2", str(caught.exception))
                self.assertNotIn("SECRET", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
