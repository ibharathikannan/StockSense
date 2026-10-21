"""Load cleaned SEC fundamentals facts into the shared-data database.

Reads the ``facts.jsonl`` written by data/import_sec_financial_statements.py (or
data/collect_sec_fundamentals.py) and replaces the contents of an additive
``sec_fundamental_facts`` table beside the verified snapshot tables, the same
way ``chunk_embeddings`` is added. The snapshot's own tables are never modified.
Each load is one transaction: readers see the old rows or the new rows, never a mix.

    python -m data.rag.load_sec_fundamentals --env-file data/.env
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re

try:
    from data.collection_common import read_jsonl
    from data.rag.build_embeddings import DEFAULT_SCHEMA, _connect
except ImportError:  # running from inside data/
    from collection_common import read_jsonl
    from rag.build_embeddings import DEFAULT_SCHEMA, _connect

DEFAULT_FACTS = Path("data/artifacts/sec_fundamentals/facts.jsonl")
TABLE = "sec_fundamental_facts"
COLUMNS = ("ticker", "cik", "concept", "period_start", "period_end", "value", "form",
           "fiscal_year", "fiscal_period", "filed", "accession")


def _schema(name: str) -> str:
    # The schema name is interpolated into SQL, so allow only snapshot-style identifiers.
    if not re.fullmatch(r"ss_[0-9a-f]{20}", name):
        raise ValueError("Schema must be a pinned snapshot schema such as ss_<20 hex chars>")
    return name


def _row(fact: dict) -> tuple:
    return (fact["ticker"], fact["cik"], fact["concept"], fact.get("start"), fact["end"],
            float(fact["val"]), fact["form"], fact.get("fy"), fact.get("fp"), fact["filed"],
            fact.get("accn"))


def load(conn, schema: str, facts: list[dict]) -> int:
    if not facts:
        raise ValueError("No facts to load; the existing table is left unchanged")
    schema = _schema(schema)
    with conn.cursor() as cur:
        cur.execute(f"""CREATE TABLE IF NOT EXISTS {schema}.{TABLE} (
                ticker        text NOT NULL,
                cik           bigint NOT NULL,
                concept       text NOT NULL,
                period_start  date,
                period_end    date NOT NULL,
                value         double precision NOT NULL,
                form          text NOT NULL,
                fiscal_year   integer,
                fiscal_period text,
                filed         date NOT NULL,
                accession     text,
                loaded_at     timestamptz NOT NULL DEFAULT now())""")
        cur.execute(f"CREATE INDEX IF NOT EXISTS {TABLE}_ticker_idx ON {schema}.{TABLE} (ticker, concept)")
        cur.execute(f"DELETE FROM {schema}.{TABLE}")
        cur.executemany(
            f"INSERT INTO {schema}.{TABLE} ({', '.join(COLUMNS)}) VALUES ({', '.join(['%s'] * len(COLUMNS))})",
            [_row(f) for f in facts])
    conn.commit()
    return len(facts)


def fetch(conn, schema: str) -> list[dict]:
    """Facts in the signal's record shape, or [] when the table does not exist yet."""
    schema = _schema(schema)
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (f"{schema}.{TABLE}",))
        if cur.fetchone()[0] is None:
            return []
        cur.execute(f"SELECT {', '.join(COLUMNS)} FROM {schema}.{TABLE}")
        rows = cur.fetchall()
    return [{"ticker": r[0], "cik": r[1], "concept": r[2],
             "start": r[3].isoformat() if r[3] else None, "end": r[4].isoformat(), "val": r[5],
             "form": r[6], "fy": r[7], "fp": r[8], "filed": r[9].isoformat(), "accn": r[10]}
            for r in rows]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--facts", type=Path, default=DEFAULT_FACTS)
    parser.add_argument("--schema", default=os.environ.get("SS_SCHEMA", DEFAULT_SCHEMA))
    args = parser.parse_args(argv)
    facts = read_jsonl(args.facts)
    import psycopg
    try:
        with _connect(args.env_file) as conn:
            count = load(conn, args.schema, facts)
    except psycopg.Error:
        print("Database operation failed. Check connection settings and credentials.")
        return 1
    print(f"Loaded {count:,} SEC fundamentals facts into {args.schema}.{TABLE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
