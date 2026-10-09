# Sentiment attribution diagnostic (P1)

Gating question for news-aware signals (DATA_GATE.md marked company sentiment BLOCKED):
are the misattributions (e.g. TEO→MS, DELL→NOW) **Alpha Vantage's** fault or **ours**?
Answer: **ours.** AV's independent per-ticker sentiment is the more defensible source, but
it is thin, so news-aware mode must abstain to baseline where AV coverage is absent.

Reproduce (read-only; needs shared-data credentials):

```bash
.venv-data/bin/python -m data.evaluation.sentiment_attribution --env-file data/.env --prompt-password
```

Evidence JSON: `data/artifacts/evaluation/sentiment_attribution.json` (gitignored).

## Evidence (schema `ss_ef82d22e57e68952a418`, 2026-10-08)

| Check | Result | Reading |
| --- | --- | --- |
| Attribution difficulty | **2,699 / 7,222 (37.4%)** associations dropped as `unavailable_ambiguous_attribution` | Our method cannot even score 37% of ticker associations |
| Gross name collisions | **0 / 4,523 (0.0%)** scored rows name a *different* universe company | The same-doc exclusion rule prevents crude name bleed |
| Local vs AV agreement (per-article) | **474 / 638 (74.3%)** sign agreement | Our local score disagrees in *sign* with AV ~26% of the time |
| Local vs AV agreement (7-day aggregate) | **54 / 77 (70.1%)**, mean\|diff\|=0.21 | Same divergence at the aggregate level |
| AV coverage | **1,035 / 4,780 (21.6%)** news docs are Alpha Vantage | Alpaca (78%) carries no per-ticker sentiment at all |
| AV `relevance_score` persisted | **No** | Dropped at collection (`collect_news.py` kept only label+score) |

## Verdict: the errors are ours

- Local sentiment is **FinBERT scored over text our own regex + sentence/list segmentation
  attributed** (`prepare_text_data.py: company_pattern`, `sentiment_inputs`). Its weak
  points: a case-sensitive bare-ticker-as-word match for ≥3-char tickers, a naive sentence
  splitter that keeps comma-lists together, and "who the sentence is *about* vs who is
  *mentioned*" being undecidable by regex.
- AV assigns sentiment **per ticker independently** at the source. It does not use our
  attribution, so the 26–30% sign disagreement is largely our error, not AV's.
- Gross name collisions are ~0%, so the gate's TEO/MS and DELL/NOW cases are **subtle
  subject-vs-mention** errors — exactly what a regex method gets wrong — not crude bleed.

## Decision for the news-aware signal (P1b)

1. **Trust AV per-ticker sentiment** (`provider_sentiment[ticker].score`) as the news
   signal. **Local FinBERT sentiment is evidence-only / experimental** and never drives the
   signal.
2. **Relevance gate** = AV's own ticker tagging (AV only tags tickers it deems relevant),
   optionally strengthened by a title mention. A *numeric* relevance threshold is
   impossible — `relevance_score` was not persisted and re-collection is out of scope.
3. **Recency**: apply the 24–72h decay weighting on AV-scored articles (`published_at` is
   present).
4. **Dedup**: collapse repeated stories by `content_hash` / document.
5. **Abstain to baseline when AV coverage is absent.** With only 21.6% AV coverage, many
   tickers have no recent AV sentiment; those get the baseline stance, no MONITOR* override.
6. **MONITOR\*** fires only on strong, recent, AV-sourced negative sentiment with enough
   AV articles — and is always surfaced as experimental/provisional.

This keeps the signal deterministic and honest: a defensible news-aware mode where AV
coverage exists, cleanly abstaining to baseline where it does not.

## Addendum (P1c, 2026-10-08): relevance recollection is blocked by entitlement

The ingestion fix to persist AV `relevance_score` is in place (`collect_news._av_records`),
but **recollecting it is not possible with the current key**: a pilot `NEWS_SENTIMENT`
request returns an entitlement notice —

> "This is a premium endpoint. You may subscribe to any of the premium plans ... to
> instantly unlock all premium endpoints."

So AV `NEWS_SENTIMENT` is now premium-gated. This is an entitlement limit, not a quota
problem (1/25 calls used; waiting does not help). Consequence for the **existing 1,035 AV
articles**: they carry `score` + `label` but **no `relevance`**, permanently, unless a
premium key is obtained and articles are re-fetched.

Decision taken: the aggregation **degrades gracefully**. `records_from_documents(docs,
default_relevance=1.0)` keeps the existing corpus with equal (assumed) relevance and sets
`relevance_assumed=True`; the resulting `news_signal` carries `relevance_available=False`,
which the explanation surfaces as a caveat. News-aware mode therefore runs today as
**AV-score + recency + dedup, equal-weighted** — and becomes true relevance-weighting the
moment a premium key is available (no code change needed). Open decision for the team:
subscribe to AV premium vs. ship the equal-weighted degraded mode.

## Resolution (P1d, 2026-10-08): switched sentiment source to Marketaux

Alpha Vantage and Finnhub both gate sentiment behind premium. **Marketaux's free
`/v1/news/all` does not** — each article's `entities[]` carry per-entity `sentiment_score`
(−1..1) and `match_score` (relevance), on all plans. That is the source we now use.

Why this fixes the attribution problem directly: Marketaux attributes sentiment **per
entity** server-side, so AAPL's score comes from AAPL's entity — we never run our regex or
FinBERT on it, which is what went wrong with AV. `match_score` (normalised `/100` to [0,1])
is the relevance weight in `S = Σ(w·r·s)/Σ(w·r)`; relevance determines *contribution*, not
override strength.

Implementation: `data/collect_marketaux_news.py` (per-symbol, provider-side sentiment,
dedup, request-budget guard, requires a `User-Agent` — Marketaux returns Cloudflare 1010
without one). `data.rag.news_sentiment` and the engine's `TRUSTED_NEWS_SOURCES` accept
`marketaux` alongside `alpha_vantage`.

Live results (90-ticker universe, 7-day window, ~90 free requests): **193 documents, 68
tickers with a relevance-weighted signal (≥2 articles), 63 engine-ready (≤72h), 3 strongly
negative** (NKE, HON, CMCSA). Fresher and cleaner than the frozen AV corpus. Artifact:
`data/artifacts/marketaux/documents.jsonl` (gitignored); persisting it to Postgres folds
into the P7 assembler.

Calibration note: observed `match_score` runs low (normalised ~0.05–0.2), so `relevance`
is used mainly as a *weight* (floor kept low); tune `AggregationConfig.relevance_floor`
against real distributions during evaluation. The equal-weighted AV path above remains a
fallback but is superseded by Marketaux as the default sentiment source.
