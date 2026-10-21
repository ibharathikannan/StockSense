"""Assemble recommendation snapshots (P7) — the nightly batch.

Implements the chain in docs/ai/OPERATIONAL_MODEL.md: for each recommendation-eligible
ticker x risk tier, combine a (placeholder) forecast + the aggregated Marketaux news
sentiment -> the hybrid signal -> retrieved evidence -> a grounded explanation, into one
RecommendationSnapshot. Snapshots are written to a JSONL artifact that the backend (P8)
loads into the application database.

The forecast is a pluggable seam fed into the hybrid engine (never the base engine directly):
when main's saved XGBoost results are available (forecasts.csv + report.json, passed via
--forecasts or found under FORECAST_RESULTS_DIR) each ticker's 10-day return, interval and
downside bound flow through `evaluate_signal` into the decision. Tickers without a saved
forecast fall back to `placeholder_forecast` and stay conservative (MONITOR / CAUTION) with a
"forecast pending" trace line; EXPLORE only unlocks when a real forecast lands.

    python -m data.rag.assemble_snapshots --env-file data/.env --forecasts <dir_or_csv>
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    from data.rag.news_sentiment import records_from_documents, build_news_signals, AggregationConfig
    from data.rag.fundamentals_signal import build_fundamentals_signals
    from data.rag.load_sec_fundamentals import fetch as fetch_fundamentals
    from data.rag.build_embeddings import DEFAULT_SCHEMA
    from data.rag.retriever import retrieve
    from data.rag.explainer import explain
    from data.rag.build_embeddings import _connect
    from backend.app.rule_engine.hybrid_engine import evaluate_signal
    from data.collection_common import read_jsonl
except ImportError:  # running from inside data/
    from rag.news_sentiment import records_from_documents, build_news_signals, AggregationConfig
    from rag.fundamentals_signal import build_fundamentals_signals
    from rag.load_sec_fundamentals import fetch as fetch_fundamentals
    from rag.build_embeddings import DEFAULT_SCHEMA
    from rag.retriever import retrieve
    from rag.explainer import explain
    from rag.build_embeddings import _connect
    from backend.app.rule_engine.hybrid_engine import evaluate_signal
    from collection_common import read_jsonl

RISK_TIERS = ["very_conservative", "conservative", "moderate", "growth", "aggressive"]
# match_score runs low (see SENTIMENT_ATTRIBUTION.md); rely on weighting, keep the floor low.
NEWS_CONFIG = AggregationConfig(relevance_floor=0.0, window_hours=168, min_articles=2)
OUTPUT = Path("data/artifacts/snapshots/snapshots.jsonl")

# Stock-return forecasts are weak (near coin-flip; see docs/ai/OPERATIONAL_MODEL.md and the
# forecasting evaluation). So the point estimate is only trusted to MOVE the stance when the
# model is directionally confident: its 10-day interval must clear zero AND the estimate must
# exceed a small noise band. Otherwise we feed the engine a neutral 0.0 — the real numbers are
# still shown in the forecast panel, and the interval still drives the uncertainty caveats, but
# a noisy small negative can no longer force a false CAUTION. Lower the band to let weaker
# forecasts count; raise it to trust the forecast less.
NEUTRAL_RETURN_BAND = 0.5   # percent; |predicted 10-day return| below this is treated as noise
FORECAST_BASIS = "development-fold estimate (experimental; XGBoost, 10-session horizon)"


def placeholder_forecast(ticker: str) -> dict:
    """Forecast seam. Returns 'pending' when no saved forecast is available for this ticker."""
    return {"return_10d": None, "lower": None, "upper": None, "model_version": None,
            "basis": "forecast pending — no saved forecast for this ticker"}


def _resolve_forecast_paths(forecasts_arg: str | None) -> tuple[Path | None, Path | None]:
    """Resolve the forecasts.csv and report.json paths from --forecasts (a dir or the csv
    itself) or, when omitted, from the FORECAST_RESULTS_DIR environment variable. Returns
    (csv_path, report_path); either element is None when not found."""
    base = forecasts_arg or os.environ.get("FORECAST_RESULTS_DIR")
    if not base:
        return None, None
    p = Path(base)
    if p.is_dir():
        return p / "forecasts.csv", p / "report.json"
    # A direct path to forecasts.csv; look for report.json alongside it.
    return p, p.with_name("report.json")


def load_forecasts(forecasts_arg: str | None) -> dict[str, dict]:
    """Map ticker -> forecast dict (percent units) from main's saved XGBoost results.

    main's forecasts.csv stores returns as fractions (0.032 = +3.2%) with the interval width
    in percentage points; the rule engine and our snapshot both use percent, so returns are
    scaled by 100 here. Returns {} when no results are available, so the assembler falls back
    to the per-ticker placeholder rather than failing.
    """
    csv_path, report_path = _resolve_forecast_paths(forecasts_arg)
    if not csv_path or not csv_path.is_file():
        return {}

    model_version = None
    if report_path and report_path.is_file():
        try:
            report = json.loads(report_path.read_text())
            meta = report.get("metadata") or report.get("model_metadata") or {}
            model_version = meta.get("selected_model")
        except (OSError, ValueError):
            model_version = None

    forecasts: dict[str, dict] = {}
    with csv_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                ticker = row["ticker"].strip().upper()
                ret = float(row["predicted_return_10d"]) * 100
                lower = float(row["lower_return"]) * 100
                upper = float(row["upper_return"]) * 100
            except (KeyError, AttributeError, TypeError, ValueError):
                continue
            forecasts[ticker] = {
                "return_10d": ret, "lower": lower, "upper": upper,
                "model_version": model_version or (row.get("model") or None),
                "basis": FORECAST_BASIS,
            }
    return forecasts


def load_forecasts_from_db(conn) -> dict[str, dict]:
    """Map ticker -> forecast dict (percent units) from the newest imported forecast batch.

    Batches are written by backend/scripts/import_forecasts.py into the application tables.
    "Newest" uses the dashboard's ordering (as_of, then generated_at), so stances and the
    forecast panel describe the same batch. Returns {} when no batch has been imported.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.forecast_batches'), to_regclass('public.forecast_results')")
        if None in cur.fetchone():
            return {}
        cur.execute("SELECT id, model FROM public.forecast_batches "
                    "ORDER BY as_of DESC, generated_at DESC LIMIT 1")
        batch = cur.fetchone()
        if batch is None:
            return {}
        cur.execute("SELECT ticker, predicted_return_10d, lower_return, upper_return "
                    "FROM public.forecast_results WHERE batch_id = %s", (batch[0],))
        rows = cur.fetchall()
    return {ticker.strip().upper(): {"return_10d": ret * 100, "lower": lower * 100, "upper": upper * 100,
                                     "model_version": batch[1], "basis": FORECAST_BASIS}
            for ticker, ret, lower, upper in rows}


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


def confident_signal_return(forecast: dict) -> tuple[float, bool]:
    """The return value fed to the engine, and whether the forecast is directionally confident.

    A weak forecast whose interval straddles zero, or whose estimate is within the noise band,
    is neutralised to 0.0 so it cannot force a CAUTION on noise. The displayed forecast numbers
    are untouched; only the stance decision uses this gated value.
    """
    r = forecast.get("return_10d")
    if r is None:
        return 0.0, False
    lower, upper = forecast.get("lower"), forecast.get("upper")
    straddles_zero = lower is not None and upper is not None and lower < 0 < upper
    if straddles_zero or abs(r) < NEUTRAL_RETURN_BAND:
        return 0.0, False
    return r, True


def build_snapshot(profile: dict, risk_profile: str, news_signal: dict | None,
                   evidence: list[dict], forecast: dict, as_of: datetime,
                   fundamentals_signal: dict | None = None) -> dict:
    """Assemble one RecommendationSnapshot (pure given its inputs)."""
    volatility = (profile.get("risk") or {}).get("volatility_1y")
    has_forecast = forecast.get("return_10d") is not None
    forecast_return, confident = confident_signal_return(forecast)
    interval = None
    lower_bound = forecast.get("lower") if has_forecast else None
    if has_forecast and forecast.get("upper") is not None and forecast.get("lower") is not None:
        interval = forecast["upper"] - forecast["lower"]

    # The hybrid engine takes the forecast (return / interval width / downside bound) and runs
    # the base engine twice around it (baseline + news-aware), so news can still only add caution.
    signal = evaluate_signal(forecast_return=forecast_return, volatility=volatility,
                             risk_profile=risk_profile, prediction_interval_width=interval,
                             forecast_lower_bound=lower_bound, news_signal=news_signal,
                             fundamentals_signal=fundamentals_signal)
    if not has_forecast:
        signal["decision_trace"].insert(
            0, "Forecast pending: no saved 10-day forecast is available for this ticker; "
               "this stance reflects volatility and news only.")
    elif not confident:
        signal["decision_trace"].insert(
            0, f"Forecast treated as neutral: the 10-day estimate ({forecast['return_10d']:+.1f}%) "
               "is within the model's uncertainty, so it does not move the stance — stock-return "
               "forecasts are weak and only a directionally confident forecast counts.")

    explanation = explain(signal, evidence, profile["ticker"])
    return {
        "ticker": profile["ticker"], "name": profile["name"], "sector": profile["sector"],
        "asset_type": profile["asset_type"], "as_of": as_of.isoformat(),
        "forecast": forecast,
        "signal": {k: signal[k] for k in ("baseline_stance", "news_aware_stance", "provisional",
                                          "decision_trace", "news_signal", "fundamentals_signal",
                                          "risk_profile")},
        "evidence": evidence,
        "explanation": explanation,
    }


def assemble(conn, profiles: list[dict], marketaux_docs: list[dict], as_of: datetime, *,
             forecasts: dict[str, dict] | None = None, tiers=RISK_TIERS,
             k: int = 3, fundamentals_records: list[dict] | None = None) -> tuple[list[dict], dict]:
    forecasts = forecasts or {}
    eligible = [p for p in profiles if p.get("recommendation_eligible")]
    tickers = [p["ticker"] for p in eligible]
    news = build_news_signals(records_from_documents(marketaux_docs), tickers, as_of, NEWS_CONFIG)
    fundamentals = build_fundamentals_signals(fundamentals_records or [], tickers, as_of)
    docs_by_ticker: dict[str, list[dict]] = {}
    for doc in marketaux_docs:
        for t in (doc.get("tickers") or []):
            docs_by_ticker.setdefault(t, []).append(doc)

    snapshots: list[dict] = []
    coverage = {"eligible": len(eligible), "skipped_no_volatility": 0, "with_news": 0,
                "with_evidence": 0, "with_forecast": 0, "with_fundamentals": 0}
    for profile in eligible:
        if (profile.get("risk") or {}).get("volatility_1y") is None:
            coverage["skipped_no_volatility"] += 1
            continue
        news_signal = news.get(profile["ticker"])
        coverage["with_news"] += int(news_signal is not None)
        fundamentals_signal = fundamentals.get(profile["ticker"])
        coverage["with_fundamentals"] += int(fundamentals_signal is not None)
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
        forecast = forecasts.get(profile["ticker"].strip().upper()) or placeholder_forecast(profile["ticker"])
        coverage["with_forecast"] += int(forecast.get("return_10d") is not None)
        for tier in tiers:
            snapshots.append(build_snapshot(profile, tier, news_signal, evidence, forecast, as_of,
                                            fundamentals_signal=fundamentals_signal))
    coverage["snapshots"] = len(snapshots)
    return snapshots, coverage


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Assemble recommendation snapshots.")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--profiles", default="data/processed/asset_profiles.json")
    parser.add_argument("--marketaux", default="data/artifacts/marketaux/documents.jsonl")
    parser.add_argument("--forecasts", default=None,
                        help="Directory holding forecasts.csv + report.json, or the forecasts.csv "
                             "itself. Defaults to the FORECAST_RESULTS_DIR env var. When neither "
                             "is set, the newest batch imported with backend/scripts/"
                             "import_forecasts.py is read from the database; with none, "
                             "tickers fall back to a 'forecast pending' placeholder.")
    parser.add_argument("--fundamentals", default=None,
                        help="Local SEC facts.jsonl to use instead of the shared-data "
                             "sec_fundamental_facts table (data/rag/load_sec_fundamentals.py).")
    parser.add_argument("--output", default=str(OUTPUT))
    parser.add_argument("--k", type=int, default=3)
    args = parser.parse_args(argv)

    profiles = json.loads(Path(args.profiles).read_text())
    marketaux_docs = read_jsonl(args.marketaux)
    # A local export, when given, overrides the database batch (as in the backend).
    forecasts = load_forecasts(args.forecasts)
    as_of = datetime.now(timezone.utc)

    import psycopg
    try:
        with _connect(args.env_file) as conn:
            if not forecasts:
                forecasts = load_forecasts_from_db(conn)
            if not forecasts:
                print("No saved forecasts found (import a batch with backend/scripts/import_forecasts.py "
                      "or set --forecasts); using the 'forecast pending' placeholder for every ticker.")
            fundamentals_records = (read_jsonl(args.fundamentals) if args.fundamentals
                                    else fetch_fundamentals(conn, DEFAULT_SCHEMA))
            if not fundamentals_records:
                print("No SEC fundamentals found (load them with data/rag/load_sec_fundamentals.py "
                      "or pass --fundamentals); the fundamentals check abstains for every ticker.")
            snapshots, coverage = assemble(conn, profiles, marketaux_docs, as_of,
                                           forecasts=forecasts, k=args.k,
                                           fundamentals_records=fundamentals_records)
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
          f"{coverage['with_forecast']} with a real forecast, {coverage['with_news']} with news, "
          f"{coverage['with_fundamentals']} with SEC fundamentals, "
          f"{coverage['with_evidence']} with evidence, "
          f"{coverage['skipped_no_volatility']} skipped for missing volatility) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
