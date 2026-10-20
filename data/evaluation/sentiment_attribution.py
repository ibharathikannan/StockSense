"""Sentiment attribution diagnostic (P1).

Answers the gating question for news-aware signals: do the sentiment misattributions the
data gate flagged (e.g. TEO->MS, DELL->NOW) come from Alpha Vantage's ticker assignments,
or from our own local attribution (regex company matching + sentence/list segmentation +
FinBERT)? The answer decides whether the news-aware signal trusts AV's per-ticker sentiment
or our local sentiment.

Read-only. Connects to the shared-data database and computes:
  A. Attribution difficulty  - share of ticker associations dropped as ambiguous.
  B. Gross name contamination - scored attributed text that names a *different* universe
                                company (tests whether crude collisions survive).
  C. Per-article agreement    - sign agreement between our local FinBERT score and AV's
                                independent per-ticker score on the same (document, ticker).
  D. Aggregate agreement      - same comparison on the 7-day aggregate rows.
  E. AV coverage              - how many tickers/docs AV actually tags (the usable gate).

Connection settings come from libpq PG* variables (loaded from the environment or an
optional env file). Point PGDATABASE at the shared-data database. Secrets are never printed.

    python -m data.evaluation.sentiment_attribution --env-file data/.env --prompt-password

Machine-readable evidence is written under data/artifacts/evaluation/ (gitignored).
"""
from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_SCHEMA = "ss_ef82d22e57e68952a418"
UNIVERSE_CSV = Path("data/asset_universe.csv")
EVIDENCE_DIR = Path("data/artifacts/evaluation")


def _short_name(name: str) -> str:
    """Company name with a leading 'The' and trailing legal suffix removed."""
    s = re.sub(r"(?i)^the\s+", "", name)
    s = re.sub(
        r"(?i)[,\s]+(?:incorporated|inc\.?|corporation|corp\.?|company|co\.?|plc|ltd\.?)(?:[,\s].*)?$",
        "",
        s,
    ).strip()
    return s if len(s) >= 4 else name


def _universe_name_patterns() -> dict[str, re.Pattern]:
    patterns: dict[str, re.Pattern] = {}
    with UNIVERSE_CSV.open() as stream:
        for row in csv.DictReader(stream):
            if row.get("asset_type") == "index":
                continue
            short = _short_name(row["name"])
            if len(short) >= 4:
                patterns[row["ticker"]] = re.compile(rf"(?i)\b{re.escape(short)}\b")
    return patterns


def _connect(args: argparse.Namespace):
    try:
        from data.collection_common import load_environment
    except ImportError:
        from collection_common import load_environment
    load_environment(args.env_file)
    missing = [n for n in ("PGHOST", "PGDATABASE", "PGUSER") if not os.environ.get(n)]
    if missing:
        print("Configure " + ", ".join(missing) + " in the environment or an env file", file=sys.stderr)
        raise SystemExit(2)
    import psycopg

    settings: dict[str, object] = {
        "autocommit": True,
        "connect_timeout": os.environ.get("PGCONNECT_TIMEOUT", "15"),
        "sslmode": os.environ.get("PGSSLMODE", "require"),
    }
    if args.prompt_password:
        settings["password"] = getpass.getpass("PostgreSQL password: ")
    return psycopg.connect(**settings)


def _payload(value) -> dict:
    return value if isinstance(value, dict) else json.loads(value)


def run(conn, schema: str) -> dict:
    conn.execute(f"SET search_path TO {schema}")
    name_pat = _universe_name_patterns()
    evidence: dict[str, object] = {"schema": schema}

    # A. Attribution difficulty.
    total = conn.execute("SELECT count(*) FROM prepared_sentiment").fetchone()[0]
    ambiguous = conn.execute(
        "SELECT count(*) FROM prepared_sentiment WHERE status <> 'scored'"
    ).fetchone()[0]
    scored = total - ambiguous
    evidence["associations"] = {
        "total": total,
        "ambiguous_dropped": ambiguous,
        "scored": scored,
        "ambiguous_rate": round(ambiguous / total, 4) if total else None,
    }

    # B. Gross name contamination + C. per-article agreement, over scored rows.
    rows = conn.execute(
        "SELECT document_id, ticker, text, payload FROM prepared_sentiment WHERE status = 'scored'"
    ).fetchall()
    contaminated = 0
    contamination_examples: list[dict] = []
    # Cache provider_sentiment per document once.
    doc_ids = sorted({doc_id for doc_id, *_ in rows})
    provider: dict[str, dict] = {}
    for doc_id in doc_ids:
        rec = conn.execute(
            "SELECT payload FROM prepared_documents WHERE document_id = %s", (doc_id,)
        ).fetchone()
        if rec:
            provider[doc_id] = (_payload(rec[0]).get("provider_sentiment") or {})

    both = agree = 0
    divergences: list[dict] = []
    for doc_id, ticker, text, payload in rows:
        text = text or ""
        foreign = [t for t, pat in name_pat.items() if t != ticker and pat.search(text)]
        if foreign:
            contaminated += 1
            if len(contamination_examples) < 6:
                contamination_examples.append(
                    {"ticker": ticker, "also_names": foreign, "text": text[:200]}
                )
        local_score = _payload(payload).get("score")
        av = provider.get(doc_id, {}).get(ticker, {})
        av_score = av.get("score")
        try:
            av_score = float(av_score) if av_score is not None else None
        except (TypeError, ValueError):
            av_score = None
        if local_score is not None and av_score is not None:
            both += 1
            if (local_score >= 0) == (av_score >= 0):
                agree += 1
            elif len(divergences) < 6:
                divergences.append(
                    {"ticker": ticker, "local": round(local_score, 3),
                     "alpha_vantage": round(av_score, 3), "text": text[:160]}
                )
    evidence["gross_name_contamination"] = {
        "scored_rows": len(rows),
        "mentioning_other_universe_company": contaminated,
        "rate": round(contaminated / len(rows), 4) if rows else None,
        "examples": contamination_examples,
    }
    evidence["per_article_agreement"] = {
        "rows_with_local_and_av": both,
        "sign_agreement": agree,
        "sign_agreement_rate": round(agree / both, 4) if both else None,
        "divergence_examples": divergences,
    }

    # D. Aggregate agreement on the 7-day rows.
    aggs = conn.execute("SELECT payload FROM prepared_sentiment_aggregates").fetchall()
    agg_both = agg_agree = 0
    abs_diffs: list[float] = []
    for (payload,) in aggs:
        p = _payload(payload)
        local, av = p.get("local_sentiment_7d"), p.get("alpha_vantage_sentiment_7d")
        if local is not None and av is not None:
            agg_both += 1
            if (local >= 0) == (av >= 0):
                agg_agree += 1
            abs_diffs.append(abs(local - av))
    evidence["aggregate_agreement"] = {
        "rows": len(aggs),
        "with_local_and_av": agg_both,
        "sign_agreement": agg_agree,
        "sign_agreement_rate": round(agg_agree / agg_both, 4) if agg_both else None,
        "mean_abs_diff": round(sum(abs_diffs) / len(abs_diffs), 4) if abs_diffs else None,
    }

    # E. AV coverage.
    av_docs = conn.execute(
        "SELECT count(*) FROM news_documents WHERE provider = 'alpha_vantage'"
    ).fetchone()[0]
    news_docs = conn.execute("SELECT count(*) FROM news_documents").fetchone()[0]
    evidence["av_coverage"] = {
        "alpha_vantage_news_docs": av_docs,
        "total_news_docs": news_docs,
        "alpha_vantage_share": round(av_docs / news_docs, 4) if news_docs else None,
        "relevance_score_persisted": False,  # dropped at collection; see collect_news.py
    }
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose sentiment attribution quality.")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--schema", default=os.environ.get("SS_SCHEMA", DEFAULT_SCHEMA))
    parser.add_argument("--prompt-password", action="store_true")
    args = parser.parse_args(argv)

    import psycopg

    try:
        with _connect(args) as conn:
            evidence = run(conn, args.schema)
    except psycopg.Error:
        print("Database operation failed. Check connection settings and credentials.", file=sys.stderr)
        return 1

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "sentiment_attribution.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )

    a = evidence["associations"]
    pa = evidence["per_article_agreement"]
    ag = evidence["aggregate_agreement"]
    cov = evidence["av_coverage"]
    print(f"Associations: {a['scored']} scored, {a['ambiguous_dropped']} ambiguous "
          f"({a['ambiguous_rate']:.1%})")
    print(f"Gross name contamination: {evidence['gross_name_contamination']['rate']:.1%} of scored rows")
    print(f"Per-article local-vs-AV sign agreement: {pa['sign_agreement']}/{pa['rows_with_local_and_av']}"
          + (f" ({pa['sign_agreement_rate']:.1%})" if pa['sign_agreement_rate'] is not None else ""))
    print(f"Aggregate local-vs-AV sign agreement: {ag['sign_agreement']}/{ag['with_local_and_av']}"
          + (f" ({ag['sign_agreement_rate']:.1%}), mean|diff|={ag['mean_abs_diff']}" if ag['sign_agreement_rate'] is not None else ""))
    print(f"AV coverage: {cov['alpha_vantage_news_docs']}/{cov['total_news_docs']} news docs "
          f"({cov['alpha_vantage_share']:.1%}); relevance_score persisted: {cov['relevance_score_persisted']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
