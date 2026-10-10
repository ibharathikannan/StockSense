# StockSense operational model (RAG + signal layer)

The contract the nightly batch and the dashboard build to. Confirmed 2026-10-09.

## The core principle: two paths out of the news corpus

The same Marketaux news is used two different ways, and they must not be conflated:

1. **Sentiment → the signal (a number).** Per-ticker Marketaux sentiment is aggregated into
   **one score per ticker** and fed to the rule engine. It *changes the stance*.
2. **Embeddings → the evidence (text).** News passages are embedded so retrieval can *cite*
   them in the "Why?" explanation. They do **not** change the stance.

Adding embeddings each day enriches what the explanation can quote; it never moves the signal.

## End-to-end flow

```
 Marketaux (nightly)                   XGBoost / baseline (separate)
 per-article, per-entity               per ticker
 sentiment_score + match_score         forecast_return, interval, volatility
        │                                     │
        ▼                                     │
 AGGREGATE per ticker                         │
 relevance-weighted (match_score),            │
 recency-decayed, deduped, windowed (7d)      │
   → one news sentiment score / ticker        │
        │                                     │
        └────────────────┬─────────────────────┘
                         ▼
               HYBRID SIGNAL ENGINE        ← sentiment enters HERE
               base engine run twice:
                 - WITHOUT news  = baseline stance (conservative)
                 - WITH the score = news-aware stance
                         │
                         ▼
           stance (EXPLORE / MONITOR / CAUTION) + decision trace
                         │
      ┌──────────────────┴────────────────────┐
      ▼                                        ▼
 RAG evidence (embeddings)               recommendation_snapshot
 cite articles in the "Why?"             stance + forecast + evidence
 — does NOT change the stance             + explanation, stamped as_of
```

## How the Marketaux score moves the stance

The aggregated per-ticker score is passed to the base rule engine as `sentiment_score`:

| Aggregated Marketaux sentiment | Resulting stance |
| --- | --- |
| ≤ −0.15 (bearish) | **CAUTION** (overrides) |
| ≥ +0.15 (bullish) + strong forecast + narrow interval + not concentrated | **EXPLORE** |
| in between / neutral | **MONITOR** |
| no eligible news (below relevance/recency/min-article gates) | abstain → forecast-only baseline |

Because the base engine reaches EXPLORE only *with* bullish sentiment, the baseline (no news)
is conservative — so news genuinely earns an EXPLORE or triggers a CAUTION.

## What the dashboard shows (confirmed)

- **The news-aware stance is the primary signal** (sentiment affects it, as intended).
- The **baseline stance is shown alongside** as "forecast-only context."
- When news changed the stance, it is flagged **provisional / experimental** — sentiment
  validation is still limited (see docs/ai/SENTIMENT_ATTRIBUTION.md). P10 will compare
  baseline vs news-aware to test whether news actually improves decisions.

## Cadence & reproducibility

Runs as a **nightly end-of-day batch** (matches the proposal's end-of-day model):

```
1. collect_marketaux_news        append the new day's news (dedup by uuid)
2. aggregate sentiment (windowed) updated news score per ticker        [moves the signal]
3. embed ONLY new news chunks     incremental, resumable                [grows evidence index]
4. evaluate_signal + assemble     regenerate recommendation_snapshots, stamped as_of
```

- **Signals move day to day** as the windowed sentiment changes — intended behaviour. Each
  snapshot's `as_of` makes any given day reproducible.
- The embedding step is **incremental** (`ON CONFLICT DO NOTHING` + a `LEFT JOIN` on missing
  rows), so a nightly run embeds only that day's ~hundreds of new articles, never the full
  corpus. The news-evidence index may be pruned (e.g. keep 90 days) if it needs capping.
- Forecast and volatility are stable between model refreshes; only the news layer moves daily.

## Submission vs live

- **Submission:** a single point-in-time snapshot is a valid demo — no daily runs required.
- **Live:** schedule the four steps above nightly after US market close.

## Current status against this model

Built: collection, aggregation, hybrid signal engine, embeddings, retrieval, explanation,
discovery. Not yet built: the **assembler (P7)** that chains aggregate → signal → evidence →
snapshot into one nightly command, and the backend/frontend that serve the snapshots.
Forecast is a **neutral placeholder** until XGBoost serving is wired (owned separately).
