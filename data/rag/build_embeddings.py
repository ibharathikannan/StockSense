"""Embed prepared_chunks into a pgvector sidecar table (P3).

Reads `prepared_chunks` from the shared-data database and embeds each chunk's text with
`sentence-transformers/all-MiniLM-L6-v2` (384-dim, mean-pooled, L2-normalised), upserting into
an additive `chunk_embeddings` table. The frozen `prepared_chunks` table is never modified.

Resumable: only chunks without an embedding for the current model are processed, so the job
can be interrupted and re-run. An HNSW cosine index is created for retrieval (P4).

    python -m data.rag.build_embeddings --env-file data/.env [--limit N] [--batch-size 256]

Connection settings come from libpq PG* variables; point PGDATABASE at the shared-data
database. Secrets are never printed.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

DEFAULT_SCHEMA = "ss_ef82d22e57e68952a418"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384
MAX_TOKENS = 256


def _connect(env_file):
    try:
        from data.collection_common import load_environment
    except ImportError:
        from collection_common import load_environment
    load_environment(env_file)
    missing = [n for n in ("PGHOST", "PGDATABASE", "PGUSER") if not os.environ.get(n)]
    if missing:
        print("Configure " + ", ".join(missing) + " in the environment or env file", file=sys.stderr)
        raise SystemExit(2)
    import psycopg

    return psycopg.connect(autocommit=False, sslmode=os.environ.get("PGSSLMODE", "require"),
                           connect_timeout=int(os.environ.get("PGCONNECT_TIMEOUT", "15")))


def _load_model():
    import torch
    from transformers import AutoModel, AutoTokenizer

    if torch.backends.mps.is_available():
        device = "mps"
    elif torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModel.from_pretrained(MODEL_NAME).to(device).eval()
    return tokenizer, model, device


def _embed(texts, tokenizer, model, device):
    import torch

    enc = tokenizer(texts, padding=True, truncation=True, max_length=MAX_TOKENS,
                    return_tensors="pt").to(device)
    with torch.no_grad():
        out = model(**enc)
    mask = enc["attention_mask"].unsqueeze(-1).float()
    summed = (out.last_hidden_state * mask).sum(1)
    counts = mask.sum(1).clamp(min=1e-9)
    mean = torch.nn.functional.normalize(summed / counts, p=2, dim=1)
    return mean.cpu().tolist()


def _ensure_schema(conn, schema):
    with conn.cursor() as cur:
        cur.execute(f"SET search_path TO {schema}, public")
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(
            f"""CREATE TABLE IF NOT EXISTS chunk_embeddings (
                    chunk_id   text PRIMARY KEY,
                    embedding  vector({EMBED_DIM}) NOT NULL,
                    model      text NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now()
                )"""
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS chunk_embeddings_hnsw "
            "ON chunk_embeddings USING hnsw (embedding vector_cosine_ops)"
        )
    conn.commit()


def run(conn, schema, batch_size, limit):
    _ensure_schema(conn, schema)
    tokenizer, model, device = _load_model()
    print(f"Model loaded on {device}; embedding in batches of {batch_size}.")

    total = 0
    last_id = ""
    start = time.monotonic()
    while True:
        if limit is not None and total >= limit:
            break
        take = batch_size if limit is None else min(batch_size, limit - total)
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")
            cur.execute(
                """SELECT c.chunk_id, c.text
                   FROM prepared_chunks c
                   LEFT JOIN chunk_embeddings e ON e.chunk_id = c.chunk_id
                   WHERE e.chunk_id IS NULL AND c.chunk_id > %s
                   ORDER BY c.chunk_id LIMIT %s""",
                (last_id, take),
            )
            rows = cur.fetchall()
        if not rows:
            break
        ids = [r[0] for r in rows]
        texts = [r[1] or "" for r in rows]
        vectors = _embed(texts, tokenizer, model, device)
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")
            cur.executemany(
                "INSERT INTO chunk_embeddings (chunk_id, embedding, model) "
                "VALUES (%s, %s::vector, %s) ON CONFLICT (chunk_id) DO NOTHING",
                [(cid, "[" + ",".join(f"{v:.6f}" for v in vec) + "]", MODEL_NAME)
                 for cid, vec in zip(ids, vectors)],
            )
        conn.commit()
        total += len(rows)
        last_id = ids[-1]
        if total % (batch_size * 10) == 0 or (limit and total >= limit):
            rate = total / max(time.monotonic() - start, 1e-9)
            print(f"  embedded {total} chunks ({rate:.0f}/s)", flush=True)

    with conn.cursor() as cur:
        cur.execute(f"SET search_path TO {schema}, public")
        cur.execute("SELECT count(*) FROM chunk_embeddings")
        embedded = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM prepared_chunks")
        chunks = cur.fetchone()[0]
    print(f"Done. {total} newly embedded this run; {embedded}/{chunks} chunks have embeddings.")
    return embedded, chunks


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Embed prepared_chunks into pgvector.")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--schema", default=os.environ.get("SS_SCHEMA", DEFAULT_SCHEMA))
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--limit", type=int, default=None, help="Embed at most N chunks (testing)")
    args = parser.parse_args(argv)

    import psycopg

    try:
        with _connect(args.env_file) as conn:
            run(conn, args.schema, args.batch_size, args.limit)
    except psycopg.Error:
        print("Database operation failed. Check connection settings and credentials.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
