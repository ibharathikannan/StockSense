"""Add fresh Marketaux news to the retrieval evidence index (P4 enhancement).

The frozen `prepared_chunks` corpus (SEC filings + older news) does not include the fresh
Marketaux news collected for the sentiment signal, so a "recent developments" query can only
surface filing boilerplate. This loads the Marketaux articles into an additive `extra_chunks`
table plus the shared `chunk_embeddings` table, and (re)creates a `rag_chunks` view that unions
`prepared_chunks` with `extra_chunks` so retrieval sees both corpora. The frozen tables are
never modified.

    python -m data.rag.embed_marketaux_evidence --env-file data/.env \
        --artifact data/artifacts/marketaux/documents.jsonl
"""
from __future__ import annotations

import argparse
import os
import sys

DEFAULT_SCHEMA = "ss_ef82d22e57e68952a418"


def _ensure(conn, schema):
    with conn.cursor() as cur:
        cur.execute(f"SET search_path TO {schema}, public")
        cur.execute(
            """CREATE TABLE IF NOT EXISTS extra_chunks (
                   chunk_id     text PRIMARY KEY,
                   document_id  text,
                   source_type  text,
                   provider     text,
                   title        text,
                   source_url   text,
                   published_at  timestamptz,
                   tickers      text[],
                   content_hash text,
                   text         text
               )"""
        )
        # Common columns across both corpora; form/section exist only on prepared_chunks.
        cur.execute(
            """CREATE OR REPLACE VIEW rag_chunks AS
               SELECT chunk_id, document_id, source_type, title, source_url, published_at,
                      tickers, content_hash, text, form, section
               FROM prepared_chunks
               UNION ALL
               SELECT chunk_id, document_id, source_type, title, source_url, published_at,
                      tickers, content_hash, text, NULL::text AS form, NULL::text AS section
               FROM extra_chunks"""
        )
    conn.commit()


def run(conn, schema, artifact, batch_size):
    try:
        from data.collection_common import read_jsonl
        from data.rag.build_embeddings import _load_model, _embed
    except ImportError:
        from collection_common import read_jsonl
        from rag.build_embeddings import _load_model, _embed

    _ensure(conn, schema)
    docs = read_jsonl(artifact)
    tokenizer, model, device = _load_model()
    print(f"Embedding {len(docs)} Marketaux documents on {device}.")

    inserted = 0
    for start in range(0, len(docs), batch_size):
        batch = docs[start:start + batch_size]
        texts = [((d.get("title") or "") + ". " + (d.get("text") or "")).strip() for d in batch]
        vectors = _embed(texts, tokenizer, model, device)
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")
            cur.executemany(
                """INSERT INTO extra_chunks (chunk_id, document_id, source_type, provider, title,
                        source_url, published_at, tickers, content_hash, text)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (chunk_id) DO NOTHING""",
                [(d["document_id"], d["document_id"], d.get("source_type", "news"),
                  d.get("provider"), d.get("title"), d.get("source_url"),
                  d.get("published_at"), d.get("tickers"), d.get("content_hash"), d.get("text"))
                 for d in batch],
            )
            cur.executemany(
                "INSERT INTO chunk_embeddings (chunk_id, embedding, model) "
                "VALUES (%s,%s::vector,%s) ON CONFLICT (chunk_id) DO NOTHING",
                [(d["document_id"], "[" + ",".join(f"{v:.6f}" for v in vec) + "]",
                  "sentence-transformers/all-MiniLM-L6-v2")
                 for d, vec in zip(batch, vectors)],
            )
        conn.commit()
        inserted += len(batch)
    print(f"Done. {inserted} Marketaux documents embedded into the evidence index.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Embed Marketaux news into the evidence index.")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--schema", default=os.environ.get("SS_SCHEMA", DEFAULT_SCHEMA))
    parser.add_argument("--artifact", default="data/artifacts/marketaux/documents.jsonl")
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args(argv)

    from data.rag.build_embeddings import _connect
    import psycopg

    try:
        with _connect(args.env_file) as conn:
            run(conn, args.schema, args.artifact, args.batch_size)
    except psycopg.Error:
        print("Database operation failed. Check connection settings and credentials.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
