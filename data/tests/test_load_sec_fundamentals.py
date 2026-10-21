"""Shared-database load/fetch of SEC fundamentals with a fake connection; no database."""
from datetime import date

import pytest

from data.rag import load_sec_fundamentals as module

SCHEMA = "ss_ef82d22e57e68952a418"
FACT = {"ticker": "AAPL", "cik": 320193, "concept": "Revenues", "start": "2024-10-01",
        "end": "2025-09-30", "val": 416.0, "form": "10-K", "fy": 2025, "fp": "FY",
        "filed": "2025-10-31", "accn": "0000320193-25-000079"}


class Cursor:
    def __init__(self, conn): self.conn = conn
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def execute(self, sql, params=None): self.conn.calls.append((" ".join(sql.split()), params))
    def executemany(self, sql, rows): self.conn.calls.append((" ".join(sql.split()), list(rows)))
    def fetchone(self): return (self.conn.table,)
    def fetchall(self): return self.conn.rows


class Connection:
    def __init__(self, table="exists", rows=()):
        self.calls, self.commits, self.table, self.rows = [], 0, table, list(rows)
    def cursor(self): return Cursor(self)
    def commit(self): self.commits += 1


def test_load_replaces_table_contents_in_one_transaction():
    conn = Connection()
    assert module.load(conn, SCHEMA, [FACT]) == 1
    statements = [sql.split(" (")[0] for sql, _ in conn.calls]
    assert statements[0].startswith(f"CREATE TABLE IF NOT EXISTS {SCHEMA}.sec_fundamental_facts")
    assert statements[2] == f"DELETE FROM {SCHEMA}.sec_fundamental_facts"
    assert conn.calls[3][1] == [("AAPL", 320193, "Revenues", "2024-10-01", "2025-09-30", 416.0, "10-K",
                                 2025, "FY", "2025-10-31", "0000320193-25-000079")]
    assert conn.commits == 1


def test_empty_input_or_unpinned_schema_changes_nothing():
    conn = Connection()
    with pytest.raises(ValueError):
        module.load(conn, SCHEMA, [])
    with pytest.raises(ValueError):
        module.load(conn, "public; DROP TABLE x", [FACT])
    assert conn.calls == [] and conn.commits == 0


def test_fetch_returns_signal_records_or_nothing_without_table():
    assert module.fetch(Connection(table=None), SCHEMA) == []
    row = ("AAPL", 320193, "Revenues", date(2024, 10, 1), date(2025, 9, 30), 416.0, "10-K", 2025, "FY",
           date(2025, 10, 31), "0000320193-25-000079")
    assert module.fetch(Connection(rows=[row]), SCHEMA) == [FACT]
