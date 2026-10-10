"""Unit tests for retrieval fusion/dedup/shaping (pure; no DB or model).

The live pgvector + keyword integration is exercised separately against the database once
embeddings exist; here we lock down the deterministic ranking and citation logic.
"""
from datetime import datetime, timezone

from data.rag.retriever import Hit, fuse, _to_evidence


def _hit(cid, chash, sim=None, text="body", title="t", stype="news"):
    return Hit(chunk_id=cid, content_hash=chash, title=title, source_type=stype,
               source_url=f"https://ex/{cid}", published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
               text=text, similarity=sim)


def test_fuse_rrf_ranks_overlap_highest():
    vector = [_hit("c1", "h1", sim=0.9), _hit("c2", "h2", sim=0.8)]
    keyword = [_hit("c2", "h2"), _hit("c3", "h3")]
    out = fuse(vector, keyword, k=5)
    hashes = [h.content_hash for h in out]
    assert hashes[0] == "h2"               # appears in both lists -> highest fused score
    assert hashes == ["h2", "h1", "h3"]     # h1 (vector rank0) outranks h3 (keyword rank1)


def test_fuse_dedups_by_content_hash_and_keeps_similarity():
    # Same story (same content hash) via two different chunk ids, vector + keyword.
    vector = [_hit("c1", "dup", sim=0.77)]
    keyword = [_hit("c2", "dup")]
    out = fuse(vector, keyword, k=5)
    assert len(out) == 1
    assert out[0].similarity == 0.77        # representative carries the vector similarity


def test_fuse_respects_k():
    vector = [_hit(f"c{i}", f"h{i}", sim=0.5) for i in range(10)]
    assert len(fuse(vector, [], k=3)) == 3


def test_to_evidence_shapes_and_truncates():
    long_text = "word " * 200
    ev = _to_evidence(_hit("c1", "h1", text=long_text, title="Headline", stype="sec"))
    assert ev["title"] == "Headline" and ev["source_type"] == "sec"
    assert ev["source_url"] == "https://ex/c1" and ev["published_at"].startswith("2026-01-01")
    assert ev["snippet"].endswith("…") and len(ev["snippet"]) <= 322
