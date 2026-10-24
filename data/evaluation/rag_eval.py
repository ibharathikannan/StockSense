"""RAG layer evaluation: retrieval precision@k / recall@k, context relevance, faithfulness.

Two read-only subcommands; reports go to data/artifacts/evaluation/rag/ (gitignored).

  retrieval   (online)  Runs the production hybrid retrieval (vector + keyword, RRF fusion)
              against the shared-data database for a fixed query set. A local cross-encoder
              (ms-marco MiniLM) judges every pooled candidate, giving relevance labels for
              precision@k, pooled recall@k and context relevance.
  generation  (offline) Scores the faithfulness of the explanations in an assembled snapshot
              file: each claim line must be entailed (local NLI cross-encoder) by the evidence
              or the decision trace the explainer was given. A negative control with one
              fabricated claim appended shows the metric can detect unsupported text.

    python -m data.evaluation.rag_eval generation
    python -m data.evaluation.rag_eval retrieval --env-file data/.env

Recall is measured against the judged pool (vector top-N union keyword top-N), the usual
TREC-style estimate: relevant chunks that neither search arm surfaces are not counted.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Callable, Optional

RELEVANCE_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
NLI_MODEL = "cross-encoder/nli-deberta-v3-small"
PROFILES = Path("data/processed/asset_profiles.json")
SNAPSHOT_DIR = Path("data/artifacts/snapshots")
OUTPUT_DIR = Path("data/artifacts/evaluation/rag")
KS = (1, 3, 5)
POOL_DEPTH = 20
RELEVANCE_THRESHOLD = 0.5
ENTAILMENT_THRESHOLD = 0.5
FABRICATED_CLAIM = "- Revenue rose 40% last quarter after the company accepted a takeover offer."

# (ticker, query, source types) — topical questions beyond the two production templates.
TOPICAL_QUERIES = [
    ("NVDA", "NVIDIA data center AI chip demand", None),
    ("AAPL", "Apple iPhone sales", None),
    ("MSFT", "Microsoft Azure cloud growth", None),
    ("TSLA", "Tesla vehicle deliveries", None),
    ("JPM", "JPMorgan net interest income", None),
]


# --- pure metrics -----------------------------------------------------------------------------

def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Relevant items in the top k divided by k (a short or empty list is penalised)."""
    return sum(1 for item in retrieved[:k] if item in relevant) / k


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> Optional[float]:
    """Share of all known relevant items found in the top k; None when nothing is relevant."""
    if not relevant:
        return None
    return sum(1 for item in retrieved[:k] if item in relevant) / len(relevant)


def context_relevance(scores: list[float]) -> Optional[float]:
    """Mean judge relevance of the contexts actually returned; None when nothing was returned."""
    return mean(scores) if scores else None


def _mean(values) -> Optional[float]:
    present = [v for v in values if v is not None]
    return round(mean(present), 4) if present else None


def evaluate_query(retrieved: list[str], pool_scores: dict[str, float], *, ks=KS,
                   threshold=RELEVANCE_THRESHOLD) -> dict:
    """Score one query's ranked result ids against judge scores for its candidate pool."""
    relevant = {item for item, score in pool_scores.items() if score >= threshold}
    result = {"retrieved": len(retrieved), "pool": len(pool_scores), "relevant_in_pool": len(relevant)}
    for k in ks:
        result[f"precision@{k}"] = precision_at_k(retrieved, relevant, k)
        result[f"recall@{k}"] = recall_at_k(retrieved, relevant, k)
        result[f"context_relevance@{k}"] = context_relevance([pool_scores[i] for i in retrieved[:k]])
    return result


def split_claims(text: str) -> list[str]:
    """Claim sentences of an explanation, without template scaffolding.

    Skipped: the stance headline (first line), section headings ending in ':', citation header
    lines ('[1] title — source, date'), the fixed abstention/provisional notes. Quoted evidence
    lines and decision-trace bullets are claims; multi-sentence lines are split into sentences.
    """
    claims = []
    for index, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if index == 0 or not line or line.endswith(":") or re.match(r"\[\d+\]", line):
            continue
        if line.startswith(("No recent news or filing evidence", "- Note:")):
            continue
        claims += _sentences(line.lstrip("-•* ").strip().strip("“”\"").strip())
    return claims


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?…])\s+|\n", text) if len(s.split()) >= 3]


def faithfulness(claims: list[str], passages: list[str],
                 entail: Callable[[list[str], str], list[float]],
                 threshold: float = ENTAILMENT_THRESHOLD) -> tuple[Optional[float], list[str]]:
    """Share of claims entailed by at least one context passage, plus the unsupported claims.

    `entail(premises, hypothesis)` returns an entailment probability per premise. A claim that
    appears verbatim (modulo whitespace) in a passage is supported without calling the model;
    only paraphrased or invented claims need NLI, which keeps a full snapshot run tractable.
    """
    if not claims:
        return None, []
    normalized = [" ".join(p.split()) for p in passages]
    unsupported = [c for c in claims
                   if not any(" ".join(c.split()) in p for p in normalized)
                   and (not passages or max(entail(passages, c)) < threshold)]
    return 1 - len(unsupported) / len(claims), unsupported


def snapshot_context(snapshot: dict) -> list[str]:
    """The passages the explainer was allowed to use: evidence and the decision trace.

    Each passage is also split into sentences: NLI models are trained on short premises and
    under-score a verbatim sentence against a long multi-sentence passage (SummaC-style fix).
    """
    passages = [f"{ev.get('title', '')}. {ev.get('snippet', '')}".strip()
                for ev in snapshot.get("evidence") or []]
    passages += list((snapshot.get("signal") or {}).get("decision_trace") or [])
    passages = [p for p in passages if p]
    return list(dict.fromkeys(passages + [s for p in passages for s in _sentences(p)]))


# --- local judge models -------------------------------------------------------------------------

def _load(name: str):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    device = ("mps" if torch.backends.mps.is_available()
              else "cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(name)
    model = AutoModelForSequenceClassification.from_pretrained(name).to(device).eval()
    return tokenizer, model, device


def _logits(loaded, firsts: list[str], seconds: list[str], batch_size: int = 32):
    import torch

    tokenizer, model, device = loaded
    out = []
    for start in range(0, len(firsts), batch_size):
        enc = tokenizer(firsts[start:start + batch_size], seconds[start:start + batch_size],
                        padding=True, truncation=True, max_length=512, return_tensors="pt").to(device)
        with torch.no_grad():
            out.append(model(**enc).logits.float().cpu())
    return torch.cat(out) if out else torch.empty(0)


def relevance_judge():
    """(query, passages) -> sigmoid relevance in [0, 1] per passage."""
    loaded = _load(RELEVANCE_MODEL)

    def judge(query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        return _logits(loaded, [query] * len(passages), passages)[:, 0].sigmoid().tolist()
    return judge


def entailment_judge():
    """(premises, hypothesis) -> entailment probability per premise."""
    loaded = _load(NLI_MODEL)
    labels = {v.lower(): k for k, v in loaded[1].config.id2label.items()}
    entail_index = labels["entailment"]

    def entail(premises: list[str], hypothesis: str) -> list[float]:
        logits = _logits(loaded, premises, [hypothesis] * len(premises))
        return logits.softmax(dim=1)[:, entail_index].tolist()
    return entail


# --- generation: faithfulness -----------------------------------------------------------------

def run_generation(snapshot_path: Path, entail, limit: Optional[int] = None) -> dict:
    seen, rows = set(), []
    with snapshot_path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            snapshot = json.loads(line)
            text = (snapshot.get("explanation") or {}).get("text") or ""
            # Snapshots repeat per risk tier; identical explanations are scored once.
            if text in seen:
                continue
            seen.add(text)
            rows.append(snapshot)
            if limit and len(rows) >= limit:
                break

    per_answer = []
    for i, snapshot in enumerate(rows, 1):
        text = snapshot["explanation"]["text"]
        passages = snapshot_context(snapshot)
        score, unsupported = faithfulness(split_claims(text), passages, entail)
        control, control_unsupported = faithfulness(split_claims(text + "\n" + FABRICATED_CLAIM),
                                                    passages, entail)
        per_answer.append({"ticker": snapshot["ticker"],
                           "risk_profile": (snapshot.get("signal") or {}).get("risk_profile"),
                           "abstained": (snapshot.get("explanation") or {}).get("abstained"),
                           "claims": len(split_claims(text)), "faithfulness": score,
                           "control_faithfulness": control,
                           "control_detected": FABRICATED_CLAIM[2:] in control_unsupported,
                           "unsupported": unsupported})
        if i % 25 == 0:
            print(f"  scored {i}/{len(rows)} explanations", flush=True)

    summary = {
        "snapshot_file": str(snapshot_path),
        "explanations": len(per_answer),
        "abstained": sum(1 for r in per_answer if r["abstained"]),
        "claims": sum(r["claims"] for r in per_answer),
        "faithfulness": _mean(r["faithfulness"] for r in per_answer),
        "control_faithfulness": _mean(r["control_faithfulness"] for r in per_answer),
        "control_detection_rate": _mean(float(r["control_detected"]) for r in per_answer),
        "fully_faithful_share": _mean(
            None if r["faithfulness"] is None else float(r["faithfulness"] == 1.0) for r in per_answer),
        "entailment_threshold": ENTAILMENT_THRESHOLD,
        "model": NLI_MODEL,
    }
    return {"summary": summary, "per_answer": per_answer}


# --- retrieval: precision / recall / context relevance ----------------------------------------

def build_queries(profiles: list[dict], tickers_limit: int) -> list[dict]:
    """Production query templates for the first eligible stocks, plus topical questions."""
    eligible = [p for p in profiles if p.get("recommendation_eligible")][:tickers_limit]
    queries = []
    for p in eligible:
        queries.append({"ticker": p["ticker"], "kind": "production-news", "source_types": ["news"],
                        "query": f"{p['name']} latest news and developments"})
        queries.append({"ticker": p["ticker"], "kind": "production-sec", "source_types": ["sec"],
                        "query": f"{p['name']} business risks and financial results"})
    known = {p["ticker"] for p in profiles}
    queries += [{"ticker": t, "kind": "topical", "source_types": s, "query": q}
                for t, q, s in TOPICAL_QUERIES if t in known]
    return queries


def run_retrieval(conn, queries: list[dict], judge, *, schema: str, as_of: datetime) -> dict:
    from data.rag.retriever import (MIN_SIMILARITY, embed_query, fuse, keyword_search,
                                    vector_search)

    per_query = []
    for i, q in enumerate(queries, 1):
        filters = dict(schema=schema, tickers=[q["ticker"]], as_of=as_of,
                       source_types=q["source_types"], limit=POOL_DEPTH)
        vector_hits = vector_search(conn, embed_query(q["query"]), **filters)
        keyword_hits = keyword_search(conn, q["query"], **filters)
        # Production abstains when the best semantic match is below the floor.
        abstained = not vector_hits or max(h.similarity or 0.0 for h in vector_hits) < MIN_SIMILARITY
        fused = [] if abstained else fuse(vector_hits, keyword_hits, max(KS))

        pool = {}
        for hit in vector_hits + keyword_hits:
            pool.setdefault(hit.content_hash or hit.chunk_id, hit.text or "")
        scores = dict(zip(pool, judge(q["query"], list(pool.values()))))
        ranked = [h.content_hash or h.chunk_id for h in fused]
        per_query.append({**q, "abstained": abstained, **evaluate_query(ranked, scores)})
        print(f"  [{i}/{len(queries)}] {q['ticker']} {q['kind']}: "
              f"P@3={per_query[-1]['precision@3']:.2f} pool_relevant={per_query[-1]['relevant_in_pool']}",
              flush=True)

    summary = {"queries": len(per_query), "abstained": sum(r["abstained"] for r in per_query),
               "as_of": as_of.isoformat(), "pool_depth": POOL_DEPTH,
               "relevance_threshold": RELEVANCE_THRESHOLD, "model": RELEVANCE_MODEL, "by_kind": {}}
    metric_names = [f"{m}@{k}" for k in KS for m in ("precision", "recall", "context_relevance")]
    for kind in ["all"] + sorted({r["kind"] for r in per_query}):
        rows = [r for r in per_query if kind == "all" or r["kind"] == kind]
        summary["by_kind"][kind] = {"queries": len(rows),
                                    **{m: _mean(r[m] for r in rows) for m in metric_names}}
    return {"summary": summary, "per_query": per_query}


# --- reports -------------------------------------------------------------------------------------

def _fmt(value) -> str:
    return "–" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)


def retrieval_markdown(report: dict) -> str:
    s = report["summary"]
    cols = [f"{m}@{k}" for m in ("precision", "recall", "context_relevance") for k in KS]
    lines = ["# RAG retrieval evaluation", "",
             f"{s['queries']} queries, {s['abstained']} abstained; pool depth {s['pool_depth']} per "
             f"search arm; relevant = {s['model']} score ≥ {s['relevance_threshold']}.", "",
             "| Query kind | n | " + " | ".join(cols) + " |",
             "|---|---|" + "---|" * len(cols)]
    for kind, row in s["by_kind"].items():
        lines.append(f"| {kind} | {row['queries']} | " + " | ".join(_fmt(row[c]) for c in cols) + " |")
    return "\n".join(lines) + "\n"


def generation_markdown(report: dict) -> str:
    s = report["summary"]
    lines = ["# RAG generation evaluation (faithfulness)", "",
             f"Source: `{s['snapshot_file']}` — {s['explanations']} distinct explanations "
             f"({s['abstained']} abstained), {s['claims']} claims; NLI model {s['model']}, "
             f"entailment ≥ {s['entailment_threshold']}.", "",
             "| Metric | Value |", "|---|---|",
             f"| Faithfulness (mean) | {_fmt(s['faithfulness'])} |",
             f"| Fully faithful explanations | {_fmt(s['fully_faithful_share'])} |",
             f"| Control: one fabricated claim appended | {_fmt(s['control_faithfulness'])} |",
             f"| Control: fabricated claim flagged unsupported | {_fmt(s['control_detection_rate'])} |",
             ""]
    unsupported = [(r["ticker"], c) for r in report["per_answer"] for c in r["unsupported"]]
    if unsupported:
        lines += ["## Unsupported claims (first 20)", ""]
        lines += [f"- **{t}**: {c}" for t, c in unsupported[:20]]
    return "\n".join(lines) + "\n"


def _write(report: dict, markdown: str, stem: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{stem}.json").write_text(json.dumps(report, indent=2, default=str))
    (output_dir / f"{stem}.md").write_text(markdown)
    print(markdown)
    print(f"Wrote {output_dir / stem}.json and .md")


def _latest_snapshot() -> Path:
    files = sorted(SNAPSHOT_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise SystemExit(f"No snapshot files under {SNAPSHOT_DIR}; pass --snapshots")
    return files[-1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the RAG layer.")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generation", help="Faithfulness of snapshot explanations (offline).")
    gen.add_argument("--snapshots", default=None, help="Snapshot JSONL (default: newest in "
                                                        f"{SNAPSHOT_DIR})")
    gen.add_argument("--limit", type=int, default=None, help="Score at most N explanations")

    ret = sub.add_parser("retrieval", help="Precision/recall/context relevance (shared DB).")
    ret.add_argument("--env-file", default=None)
    ret.add_argument("--schema", default=None)
    ret.add_argument("--profiles", default=str(PROFILES))
    ret.add_argument("--tickers", type=int, default=10, help="Eligible tickers to template")
    ret.add_argument("--as-of", default=None, help="ISO timestamp; default now (UTC)")
    args = parser.parse_args(argv)
    output_dir = Path(args.output_dir)

    if args.command == "generation":
        path = Path(args.snapshots) if args.snapshots else _latest_snapshot()
        report = run_generation(path, entailment_judge(), args.limit)
        _write(report, generation_markdown(report), "generation_report", output_dir)
        return 0

    import psycopg
    from data.rag.build_embeddings import _connect
    from data.rag.retriever import DEFAULT_SCHEMA

    as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc)
    queries = build_queries(json.loads(Path(args.profiles).read_text()), args.tickers)
    judge = relevance_judge()
    try:
        with _connect(args.env_file) as conn:
            report = run_retrieval(conn, queries, judge, schema=args.schema or DEFAULT_SCHEMA,
                                   as_of=as_of)
            conn.rollback()  # read-only: discard the session-level SETs
    except psycopg.Error:
        print("Database operation failed. Check connection settings and credentials.", file=sys.stderr)
        return 1
    _write(report, retrieval_markdown(report), "retrieval_report", output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
