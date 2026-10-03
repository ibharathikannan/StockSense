# Independent numeric data gate — 2026-10-03

The user authorized this independent gate after collection/preparation. This
review reads local datasets and source code; it does not change datasets, fit
preprocessing, train models, make provider requests, or verify the remote database.
The evaluator implemented independent calculations rather than reusing the
feature-builder or preparation validators.

## Decisions by intended use

| Intended use | Decision | Required conditions or blocker |
| --- | --- | --- |
| Price-only offline forecasting research on the fixed 87-asset universe | **CONDITIONAL** | After-close cutoff, explicit predictors, training-only preprocessing, missing-RSI handling, purged temporal folds, immutable dataset version and limited claims |
| Historically point-in-time macro-enriched comparison | **BLOCKED** | Revised macro values and proxy release dates lack verified historical vintages |
| Current forecast serving | **BLOCKED** | Prices end September 18; current serving needs a refresh/freshness contract and separately validated model/service |
| Claims about generalization to the historical broad market | **BLOCKED for that claim** | Current selected universe omits historical/dead assets; universe-membership history and a broader validation universe are absent |

A blocked macro or broad-market claim does not block an explicitly scoped
price-only offline experiment. No models or retrieval were authorized here.

## Reproducible evidence

```bash
.venv-data/bin/python data/evaluation/numeric_gate.py
# Equivalent module invocation:
.venv-data/bin/python -m data.evaluation.numeric_gate
```

Evidence is written only to ignored
`data/artifacts/evaluation/numeric_gate.json`. It includes all six source SHA-256
hashes, complete schemas, ticker coverage, formula errors, missingness and fold
counts. Inputs are hashed before and after; all six remained unchanged.
The baseline and price-candidate hashes are both
`a702f105b059abf3f85c2e4cab934e319ed786c44bf92511a7bcc597723c3594`.
The script exits 1 for checked integrity failures, 2 when required files/schema
prevent completion, and 0 for successful execution with per-use-case decisions;
exit 0 is not an unconditional readiness approval. Numeric disagreement and
NaN disagreement detection are exercised by synthetic comparisons at startup.

## Findings

- **PASS — identities and coverage:** 91 universe assets (80 stocks, 10 ETFs,
  one index), 135,593 raw bars across 91 tickers, September 1, 2020–September 18,
  2026. Feature tables contain 110,229 rows, September 1, 2021–September 18,
  2026, across exactly 87 eligible assets. CEG, GEV and FPS are excluded according
  to the universe flags; VIX is context-only. No duplicate ticker/date, universe
  ticker or macro series/observation keys exist. No universe asset lacks raw data.
- **PASS — session alignment:** every asset has all SPY sessions within its own
  observed life. VIX has two additional dates; these do not create asset feature
  rows. This is an internal benchmark-calendar check, not independently verified
  exchange-calendar completeness.
- **PASS — basic price integrity:** no missing/nonfinite raw fields, nonpositive
  OHLC/adjusted closes, invalid OHLC ranges, negative volumes or weekend bars.
  The only zero-volume rows are all 1,521 VIX rows, which is expected for an index
  and excluded from forecast assets.
- **PASS — independent feature calculations:** all **34** ticker-level fields
  checked across all 110,229 feature rows, including adjusted OHLC, rolling
  returns/indicators, lags, volumes and target, have zero mismatches at 1e-10
  absolute/relative tolerance. Maximum absolute error is 5.11e-15. All four SPY/VIX
  context fields match date-keyed raw calculations. Both candidates preserve the
  baseline rows, target and baseline columns exactly.
- **PASS — label maturity:** 109,359 labels match the adjusted-price ratio at the
  tenth subsequent observed session. The remaining 870 rows are exactly ten per
  asset; all training flags agree. The last labeled origin is September 3, 2026.
  No labeled endpoint exceeds the source snapshot. These labels are overlapping
  outcomes, not 109,359 independent observations.
- **CONDITIONAL — feature cutoff:** same-date close, volume, SPY and VIX are
  available only after the applicable session closes and the provider finalizes
  bars. They are unsuitable for a before-close prediction without an additional
  shift. The source has exchange dates, not verified delivery timestamps.
  Independent truncated-history calculations at raw row 700 for AAPL, NVDA and
  SPY show zero changes in all pre-cutoff predictor vectors; source-code inspection
  found forward shifting only in the label. This proves causal numeric calculation
  on the fixed downloaded history, not authentic historical provider vintages.
- **CONDITIONAL — missing RSI:** 14 feature rows have missing RSI. Every one is a
  complete 14-session window with zero average loss, not missing prices or warmup.
  The formula replaces a zero denominator with NaN instead of yielding RSI=100.
  Define a consistent policy before training: a separately reviewed formula
  correction or training-fold-only imputation with a missing indicator. Do not
  silently drop different rows for different model comparisons.
- **CONDITIONAL — corporate actions:** 23 split rows and 1,630 dividend rows are
  retained. Adjusted OHLC uses `Adj Close/Close`; returns and labels use adjusted
  close. Largest absolute adjusted return on a split row is 6.46%, so no obvious
  mechanical split discontinuity remains. Raw volume is not dividend adjusted.
  One forecast-eligible bar has an absolute adjusted return over 50%: BE on
  November 15, 2024, +59.19%; five others are VIX context. These are flags for
  verification, not evidence of corruption; do not trim legitimate tails.
  Downloaded adjusted prices can change retrospectively with future actions;
  absolute prices and technical levels do not constitute an as-of-vintage backtest.
  Specify the total-return-adjusted target and freeze this snapshot for comparison.
- **PASS for proxy mechanics / BLOCKED for historical vintage truth — macro:**
  5,345 observations, with availability lags exactly DFF=1 day, DGS10=1 day,
  CPI=50 days and VIXCLS=0 days. No availability precedes observation; all four
  macro columns match independent backward joins using those proxy dates, with
  zero future proxy dates selected. All `realtime_end` values are null; proxies
  do not establish initial-release values or intraday availability. CPI has all
  72 consecutive months September 2020–August 2026; 3,045 missing CPI-YoY feature
  rows come from insufficient first-year CPI history and availability lag.
  Missingness is not an excuse to backfill future values. Preserve this candidate
  for a clearly labeled revised-data sensitivity experiment, or obtain genuine
  release/vintage data before asserting point-in-time macro gains.

## Required experimental contract before fitting PCA or models

1. Freeze the price-only source hashes and use a positive predictor allowlist.
   Exclude target, training flag, future endpoints, action fields, identifiers as
   uncontrolled numeric values, and all recent text/sentiment from historical
   training. Ticker/category encodings must have a defined held-out behavior.
2. State after-close origin and adjusted 10-session return semantics; simulate
   any trade only at a subsequent executable price, with a separately defined
   evaluation contract. Same-close fills cannot be assumed.
3. Use common date boundaries across all tickers and expanding temporal folds.
   Include a row in training only if its **label endpoint is strictly before the
   first validation/test prediction origin**. Do not shuffle rows or split
   tickers' dates independently. At each illustrated annual boundary below,
   870 rows must be removed from the naive training set (ten per asset).
4. Fit imputation, encoding, scaling and optional PCA inside each training fold;
   tune only on development folds. Keep the original-feature baseline and the
   same scored origins/targets across competing models. LDA discriminant analysis
   is not appropriate to this continuous target without a separate classification
   task. No global preprocessing was fitted by this audit.
5. Reserve the 2026 period as an untouched test if it has not influenced model
   choices; 2024 and 2025 may be expanding development folds. If these periods
   were already used for tuning outside this review, choose a new holdout.
   Any calibration/validation labels used in fitting or selection must also mature
   before the held-out period. Dependence across overlapping labels requires
   date-block uncertainty estimates and per-asset reporting, not IID standard errors.

| Evaluation period | Naive prior training rows | Purged train overlap | Mature training rows | Purged evaluation tail | Mature evaluation rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2024 | 50,982 | 870 | 50,112 | 870 | 21,054 |
| 2025 | 72,906 | 870 | 72,036 | 870 | 20,880 |
| 2026 through September 18 | 94,656 | 870 | 93,786 | 0 | 14,703 |

Evaluation origins are also excluded when their label endpoints exceed the
window end, preventing 2025 model selection from consuming 2026 holdout outcomes.
These are illustrative split counts, not approved final splits or trained experiments. The September
unlabeled tail must remain excluded from scoring. No remote checks, source
verification of the BE outlier, exchange-calendar validation, model fairness
experiment, preprocessing fit or forecasting run occurred. Such limits remain
explicit rather than being converted into claims that the data is pristine.

## Evaluator validation

Both standalone and module invocations completed with the same integrity result.
A temporary fixture changed one known target by +0.1 while retaining the other
inputs: the public CLI detected exactly one target mismatch, marked price-only
research BLOCKED, and exited 1. A missing-input directory exited 2 and issued no
readiness pass. The fixture was deleted; original sources were untouched.
