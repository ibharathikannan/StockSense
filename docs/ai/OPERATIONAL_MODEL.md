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

The hybrid engine (`hybrid_engine.evaluate_signal`) runs the base engine twice — once without
news (baseline) and once with the aggregated per-ticker `sentiment_score` — and then applies one
safety rule: **unvalidated news may only make the stance MORE cautious, never more optimistic.**
The operative stance is the more cautious of the two runs.

| Aggregated Marketaux sentiment | Effect on the stance |
| --- | --- |
| ≤ −0.15 (bearish), eligible | may **lower** the stance toward **CAUTION** (flagged provisional / experimental) |
| ≥ +0.15 (bullish) | shown as positive context, but **never raises** the stance and never softens a CAUTION |
| in between / neutral | no change |
| no eligible news (below relevance/recency/min-article gates) | abstain → forecast-only baseline |

Because the sentiment signal is not yet validated (see docs/ai/SENTIMENT_ATTRIBUTION.md), it is
only ever allowed to add caution. The baseline (no news) already needs bullish sentiment to reach
EXPLORE, so in practice today's stances are MONITOR or CAUTION; letting news earn EXPLORE is a P10
decision, once validation justifies trusting positive sentiment.

## How SEC fundamentals move the stance

After the news step, `evaluate_signal` applies an optional point-in-time SEC fundamentals signal
(`data/rag/fundamentals_signal.py`, from XBRL facts collected by
`data/collect_sec_fundamentals.py`). Unlike news, the user authorized fundamentals to move the
stance in **both directions**, one step at most:

| Fundamentals rating | Effect on the stance |
| --- | --- |
| weak (score ≤ −0.4) | one step **more cautious**: EXPLORE → MONITOR, MONITOR → CAUTION (provisional) |
| strong (score ≥ +0.6) | may raise **MONITOR → EXPLORE** (provisional) |
| neutral | no change |
| abstain (ETF, < 3 metrics, latest fiscal year > ~15 months old, filed after as-of) | no change |

Strong fundamentals never lift a CAUTION (negative forecast, volatility above the risk profile,
or news-driven caution), never upgrade when the forecast interval is missing (the "forecast
pending" MONITOR cap is kept), and never upgrade under sector concentration. Metrics are revenue
growth, operating margin, free-cash-flow margin, current ratio and long-term debt-to-equity, each
strong/neutral/weak on fixed, sector-agnostic thresholds; the score is their mean. Only facts
filed on or before the snapshot's as-of date are used, and later restatements never apply
backwards. These thresholds are **unvalidated**, so every stance they change is provisional and
the `*` marker covers both news- and fundamentals-driven changes. Because most current forecasts
are neutralised to 0 by the confidence gate, strong fundamentals are in practice the main route
to EXPLORE; validating them against later outcomes is outstanding.

## What the dashboard shows (confirmed)

- **The news-aware stance is the primary signal**, but news can only add caution — it never
  upgrades the forecast-only baseline.
- The **baseline stance is shown alongside** as "forecast-only context."
- When news *lowered* the stance, it is flagged **provisional / experimental** — sentiment
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
- **Postgres is the accumulating news store.** The collector's `documents.jsonl` lives on an
  ephemeral runner, so step 3 also keeps each article's `provider_sentiment` and `available_at`
  on `extra_chunks` (append-only; nothing stored is deleted or rewritten). The company detail
  page reads the most recent news and sentiment from these tables directly. Step 4 reads the last 30 days of stored Marketaux articles back and merges
  tonight's file over them, so the 7-day sentiment window spans several nights and survives a
  failed collection or a manual assemble. "Recent news" evidence is the newest articles from
  Marketaux and semantic retrieval combined.
- Forecast and volatility are stable between model refreshes; only the news layer moves daily.

## Submission vs live

- **Submission:** a single point-in-time snapshot is a valid demo — no daily runs required.
- **Live:** schedule the four steps above nightly after US market close.

## Current status against this model

Built: collection, aggregation, hybrid signal engine, embeddings, retrieval, explanation,
discovery, the **assembler (P7)** (aggregate → forecast → signal → evidence → snapshot), and the
backend/frontend that serve the snapshots (the "Discover" screens at `/api/discovery`).

Forecast: the assembler now consumes the team's saved XGBoost results merged from `main`
(`forecasts.csv` + `report.json`, passed via `--forecasts` or `FORECAST_RESULTS_DIR`). Returns
are stored as fractions there and scaled to percent for the rule engine; each ticker's 10-day
return, interval width and downside bound feed `evaluate_signal`. Tickers with no saved forecast
fall back to a per-ticker "forecast pending" placeholder and stay conservative. The forecast
model itself is owned separately; this layer only reads its provisioned results.

Because stock-return forecasts are weak (near coin-flip), the point estimate is **confidence
gated** before it can move the stance (`confident_signal_return`): it only counts when the 10-day
interval clears zero and the magnitude exceeds a small noise band (`NEUTRAL_RETURN_BAND`, 0.5pp).
Otherwise it is fed to the engine as a neutral 0.0 — the real numbers still appear in the forecast
panel and the interval still drives the uncertainty caveats, but a noisy small negative can no
longer force a false CAUTION. Lower the band to trust weaker forecasts; raise it to trust less.
