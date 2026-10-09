"""Hybrid evidence retrieval over the embedded chunk corpus (P4).

Combines pgvector semantic search (HNSW cosine over `chunk_embeddings`) with Postgres
keyword search (full-text over `prepared_chunks`), fuses the two rankings with Reciprocal
Rank Fusion, deduplicates repeated stories by content hash, and returns cited Evidence.
Abstains (returns an empty list) when nothing clears a minimum semantic similarity — the
caller treats that as "no eligible evidence" and the explainer declines to invent a reason.

Provenance (title, source_type, source_url, published_at) travels with every passage so the
explanation can cite it. Query embeddings use the same model as the index
(`sentence-transformers/all-MiniLM-L6-v2`).

    from data.rag.retriever import retrieve
    evidence = retrieve(conn, "why is sentiment weak", tickers=["AAPL"], as_of=as_of, k=5)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

DEFAULT_SCHEMA = "ss_ef82d22e57e68952a418"
SNIPPET_CHARS = 320
RRF_K = 60                 # reciprocal-rank-fusion damping constant
MIN_SIMILARITY = 0.30      # cosine similarity floor below which we abstain

_MODEL = None              # lazily loaded (tokenizer, model, device)


@dataclass
class Hit:
    chunk_id: str
    content_hash: str
    title: str
    source_type: str
    source_url: str
    published_at: Optional[datetime]
    text: str
    form: Optional[str] = None           # SEC form (10-K, 8-K, ...) for a citation-title fallback
    similarity: Optional[float] = None   # cosine similarity for vector hits


def _search_path(cur, schema: str) -> None:
    cur.execute(f"SET search_path TO {schema}, public")


def embed_query(text: str) -> str:
    """Embed a query string and return it as a pgvector literal '[...]'."""
    global _MODEL
    if _MODEL is None:
        from data.rag.build_embeddings import _load_model
        _MODEL = _load_model()
    from data.rag.build_embeddings import _embed
    tokenizer, model, device = _MODEL
    vector = _embed([text], tokenizer, model, device)[0]
    return "[" + ",".join(f"{v:.6f}" for v in vector) + "]"


def _filters(tickers: Optional[list[str]], as_of: Optional[datetime], source_types: Optional[list[str]]):
    """Build a WHERE fragment + params shared by both searches."""
    clauses, params = [], []
    if tickers:
        clauses.append("c.tickers && %s::text[]")
        params.append(list(tickers))
    if as_of is not None:
        clauses.append("c.published_at <= %s")
        params.append(as_of)
    if source_types:
        clauses.append("c.source_type = ANY(%s::text[])")
        params.append(list(source_types))
    where = (" AND " + " AND ".join(clauses)) if clauses else ""
    return where, params


def vector_search(conn, query_vector: str, *, schema=DEFAULT_SCHEMA, tickers=None, as_of=None,
                  source_types=None, limit=20) -> list[Hit]:
    where, params = _filters(tickers, as_of, source_types)
    sql = f"""
        SELECT c.chunk_id, c.content_hash, c.title, c.source_type, c.source_url,
               c.published_at, c.text, c.form, 1 - (e.embedding <=> %s::vector) AS similarity
        FROM chunk_embeddings e
        JOIN rag_chunks c ON c.chunk_id = e.chunk_id
        WHERE TRUE{where}
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s
    """
    with conn.cursor() as cur:
        _search_path(cur, schema)
        # Filtered HNSW search: without iterative scan the index returns a fixed candidate
        # pool and THEN applies the ticker/date filter, which can yield 0 rows when a ticker's
        # chunks are not in the global nearest set. Iterative scan keeps scanning until enough
        # filtered rows are found. (pgvector >= 0.8.)
        cur.execute("SET hnsw.iterative_scan = 'relaxed_order'")
        cur.execute("SET hnsw.ef_search = 100")
        cur.execute(sql, [query_vector, *params, query_vector, limit])
        return [Hit(*row[:7], form=row[7], similarity=row[8]) for row in cur.fetchall()]


def keyword_search(conn, query: str, *, schema=DEFAULT_SCHEMA, tickers=None, as_of=None,
                   source_types=None, limit=20) -> list[Hit]:
    where, params = _filters(tickers, as_of, source_types)
    sql = f"""
        SELECT c.chunk_id, c.content_hash, c.title, c.source_type, c.source_url,
               c.published_at, c.text, c.form
        FROM rag_chunks c
        WHERE to_tsvector('english', c.text) @@ websearch_to_tsquery('english', %s){where}
        ORDER BY ts_rank(to_tsvector('english', c.text),
                         websearch_to_tsquery('english', %s)) DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        _search_path(cur, schema)
        cur.execute(sql, [query, *params, query, limit])
        return [Hit(*row[:7], form=row[7]) for row in cur.fetchall()]


def fuse(vector_hits: list[Hit], keyword_hits: list[Hit], k: int) -> list[Hit]:
    """Reciprocal Rank Fusion of two ranked lists, deduped by content hash.

    Keeps, per content hash, the representative with the best combined RRF score. A chunk's
    similarity (from the vector list) is preserved so the caller can apply the floor.
    """
    scores: dict[str, float] = {}
    best: dict[str, Hit] = {}
    for ranked in (vector_hits, keyword_hits):
        for rank, hit in enumerate(ranked):
            key = hit.content_hash or hit.chunk_id
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            # Prefer a representative that carries a similarity (vector hit).
            if key not in best or (hit.similarity is not None and best[key].similarity is None):
                best[key] = hit
    ordered = sorted(best.values(), key=lambda h: scores[h.content_hash or h.chunk_id], reverse=True)
    return ordered[:k]


def _title(hit: Hit) -> str:
    """A human-readable citation title, falling back to form/source when none is stored."""
    if hit.title:
        return hit.title
    year = hit.published_at.year if hit.published_at else None
    if hit.source_type == "sec" and hit.form:
        return f"{hit.form} filing" + (f" ({year})" if year else "")
    return (hit.source_type or "source").upper()


def _to_evidence(hit: Hit) -> dict:
    snippet = (hit.text or "").strip()
    if len(snippet) > SNIPPET_CHARS:
        snippet = snippet[:SNIPPET_CHARS].rsplit(" ", 1)[0] + "…"
    return {
        "title": _title(hit),
        "source_type": hit.source_type or "",
        "published_at": hit.published_at.isoformat() if hit.published_at else None,
        "source_url": hit.source_url or "",
        "snippet": snippet,
    }


def retrieve(conn, query: str, *, schema=DEFAULT_SCHEMA, tickers=None, as_of=None,
             source_types=None, k=5, min_similarity=MIN_SIMILARITY, candidates=20) -> list[dict]:
    """Return up to `k` cited Evidence dicts, or [] to abstain.

    Abstains when the best semantic match is below `min_similarity` (the corpus has nothing
    relevant), so the explainer never grounds an answer in off-topic passages.
    """
    query_vector = embed_query(query)
    vector_hits = vector_search(conn, query_vector, schema=schema, tickers=tickers, as_of=as_of,
                                source_types=source_types, limit=candidates)
    if not vector_hits or max((h.similarity or 0.0) for h in vector_hits) < min_similarity:
        return []
    keyword_hits = keyword_search(conn, query, schema=schema, tickers=tickers, as_of=as_of,
                                  source_types=source_types, limit=candidates)
    fused = fuse(vector_hits, keyword_hits, k)
    return [_to_evidence(h) for h in fused]
