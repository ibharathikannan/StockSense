"""Assemble recommendation snapshots (P7) — the nightly batch.

Implements the chain in docs/ai/OPERATIONAL_MODEL.md: for each recommendation-eligible
ticker x risk tier, combine a (placeholder) forecast + the aggregated Marketaux news
sentiment -> the hybrid signal -> retrieved evidence -> a grounded explanation, into one
RecommendationSnapshot. Snapshots are written to a JSONL artifact that the backend (P8)
loads into the application database.

The forecast is a pluggable seam: `placeholder_forecast` returns "pending" today; swap it for
the XGBoost results (once that serving is merged) with no other change. With the placeholder,
signals are conservative (MONITOR / CAUTION); EXPLORE unlocks when a real forecast lands.

    python -m data.rag.assemble_snapshots --env-file data/.env
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from data.rag.news_sentiment import records_from_documents, build_news_signals, AggregationConfig
    from data.rag.retriever import retrieve
    from data.rag.explainer import explain
    from data.rag.build_embeddings import _connect
    from backend.app.rule_engine.hybrid_engine import evaluate_signal
    from data.collection_common import read_jsonl
except ImportError:  # running from inside data/
    from rag.news_sentiment import records_from_documents, build_news_signals, AggregationConfig
    from rag.retriever import retrieve
    from rag.explainer import explain
    from rag.build_embeddings import _connect
    from backend.app.rule_engine.hybrid_engine import evaluate_signal
    from collection_common import read_jsonl

RISK_TIERS = ["very_conservative", "conservative", "moderate", "growth", "aggressive"]
# match_score runs low (see SENTIMENT_ATTRIBUTION.md); rely on weighting, keep the floor low.
NEWS_CONFIG = AggregationConfig(relevance_floor=0.0, window_hours=168, min_articles=2)
OUTPUT = Path("data/artifacts/snapshots/snapshots.jsonl")


def placeholder_forecast(ticker: str) -> dict:
    """Forecast seam. Returns 'pending' until XGBoost serving is wired in."""
    return {"return_10d": None, "lower": None, "upper": None, "model_version": None,
            "basis": "placeholder — pending XGBoost serving"}


def _parse_dt(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def marketaux_news_evidence(docs: list[dict], ticker: str, as_of: datetime, limit: int = 3) -> list[dict]:
    """Recent Marketaux articles for a ticker as Evidence, carrying each article's own
    sentiment (so the UI can flag good/bad) and a real headline. Most recent first; no
    look-ahead; deduped by URL."""
    items, seen = [], set()
    for doc in docs:
        if ticker not in (doc.get("tickers") or []):
            continue
        published = _parse_dt(doc["published_at"])
        available = _parse_dt(doc.get("available_at") or doc["published_at"])
        if published > as_of or available > as_of:
            continue
        key = doc.get("source_url") or doc.get("content_hash") or doc.get("document_id")
        if key in seen:
            continue
        seen.add(key)
        payload = (doc.get("provider_sentiment") or {}).get(ticker) or {}
        try:
            sentiment = float(payload.get("score"))
        except (TypeError, ValueError):
            sentiment = None
        snippet = (doc.get("text") or "").strip()
        items.append((published, {
            "title": doc.get("title") or "", "source_type": "news",
            "published_at": doc["published_at"], "source_url": doc.get("source_url") or "",
            "snippet": snippet[:500], "sentiment": sentiment,
        }))
    items.sort(key=lambda pair: pair[0], reverse=True)
    return [evidence for _, evidence in items[:limit]]


def build_snapshot(profile: dict, risk_profile: str, news_signal: dict | None,
                   evidence: list[dict], forecast: dict, as_of: datetime) -> dict:
    """Assemble one RecommendationSnapshot (pure given its inputs)."""
    volatility = (profile.get("risk") or {}).get("volatility_1y")
    has_forecast = forecast.get("return_10d") is not None
    forecast_return = forecast["return_10d"] if has_forecast else 0.0
    interval = None
    if has_forecast and forecast.get("upper") is not None and forecast.get("lower") is not None:
        interval = forecast["upper"] - forecast["lower"]

    signal = evaluate_signal(forecast_return=forecast_return, volatility=volatility,
                             risk_profile=risk_profile, prediction_interval_width=interval,
                             news_signal=news_signal)
    if not has_forecast:
        signal["decision_trace"].insert(
            0, "Forecast pending: the 10-day forecast is not yet available (XGBoost serving not "
               "wired); this stance reflects volatility and news only.")

    explanation = explain(signal, evidence, profile["ticker"])
    return {
        "ticker": profile["ticker"], "name": profile["name"], "sector": profile["sector"],
        "asset_type": profile["asset_type"], "as_of": as_of.isoformat(),
        "forecast": forecast,
        "signal": {k: signal[k] for k in ("baseline_stance", "news_aware_stance", "provisional",
                                          "decision_trace", "news_signal", "risk_profile")},
        "evidence": evidence,
        "explanation": explanation,
    }


def assemble(conn, profiles: list[dict], marketaux_docs: list[dict], as_of: datetime, *,
             tiers=RISK_TIERS, k: int = 3) -> tuple[list[dict], dict]:
    eligible = [p for p in profiles if p.get("recommendation_eligible")]
    tickers = [p["ticker"] for p in eligible]
    news = build_news_signals(records_from_documents(marketaux_docs), tickers, as_of, NEWS_CONFIG)
    docs_by_ticker: dict[str, list[dict]] = {}
    for doc in marketaux_docs:
        for t in (doc.get("tickers") or []):
            docs_by_ticker.setdefault(t, []).append(doc)

    snapshots: list[dict] = []
    coverage = {"eligible": len(eligible), "skipped_no_volatility": 0, "with_news": 0,
                "with_evidence": 0}
    for profile in eligible:
        if (profile.get("risk") or {}).get("volatility_1y") is None:
            coverage["skipped_no_volatility"] += 1
            continue
        news_signal = news.get(profile["ticker"])
        coverage["with_news"] += int(news_signal is not None)
        # Evidence is independent of risk tier, so retrieve once per ticker. News leads (it is
        # readable and current); filings are supporting context, so fewer and after the news.
        # News comes straight from Marketaux (clean headlines + per-article sentiment); fall
        # back to semantic news retrieval only when Marketaux has nothing for this ticker.
        news_ev = marketaux_news_evidence(docs_by_ticker.get(profile["ticker"], []),
                                          profile["ticker"], as_of, limit=3)
        if not news_ev:
            news_ev = retrieve(conn, f"{profile['name']} latest news and developments",
                               tickers=[profile["ticker"]], as_of=as_of, source_types=["news"],
                               k=3, min_similarity=0.25)
        sec_ev = retrieve(conn, f"{profile['name']} business risks and financial results",
                          tickers=[profile["ticker"]], as_of=as_of, source_types=["sec"], k=2)
        evidence = news_ev + sec_ev
        coverage["with_evidence"] += int(bool(evidence))
        forecast = placeholder_forecast(profile["ticker"])
        for tier in tiers:
            snapshots.append(build_snapshot(profile, tier, news_signal, evidence, forecast, as_of))
    coverage["snapshots"] = len(snapshots)
    return snapshots, coverage


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Assemble recommendation snapshots.")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--profiles", default="data/processed/asset_profiles.json")
    parser.add_argument("--marketaux", default="data/artifacts/marketaux/documents.jsonl")
    parser.add_argument("--output", default=str(OUTPUT))
    parser.add_argument("--k", type=int, default=3)
    args = parser.parse_args(argv)

    profiles = json.loads(Path(args.profiles).read_text())
    marketaux_docs = read_jsonl(args.marketaux)
    as_of = datetime.now(timezone.utc)

    import psycopg
    try:
        with _connect(args.env_file) as conn:
            snapshots, coverage = assemble(conn, profiles, marketaux_docs, as_of, k=args.k)
    except psycopg.Error:
        print("Database operation failed. Check connection settings and credentials.")
        return 1

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for snap in snapshots:
            fh.write(json.dumps(snap) + "\n")
    print(f"Assembled {coverage['snapshots']} snapshots "
          f"({coverage['eligible']} eligible tickers x {len(RISK_TIERS)} tiers; "
          f"{coverage['with_news']} with news, {coverage['with_evidence']} with evidence, "
          f"{coverage['skipped_no_volatility']} skipped for missing volatility) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
