# Offline return forecasting and uncertainty

The forecasting module implements an experimental price-only pipeline. The
separately authorized web integration displays validated saved results for an
explicit content-selected shortlist. Neither component writes to PostgreSQL,
refreshes prices, or claims a validated live forecasting service. The repository's
current data ends on 2026-09-18.

## Model decision

The Colab experiments tried Ridge, Elastic Net, forests, boosting, PCA and
ensembles. They did not establish consistent improvement over simple baselines.
The user explicitly requested XGBoost for the application. The default
`--model xgboost` therefore selects within that family, rather than claiming it
won against all models. No Transformer, macro, SEC, news or sentiment predictors
are included.

XGBoost candidates use 1, 10 or 50 boosting rounds. Inner-window MAE selects the
candidate, with RMSE as tie-breaker. `--model auto` additionally considers Ridge
alpha 100/1000 and training mean/median constants. `--model ridge` selects only
between the Ridge candidates; `mean` and `median` request a constant explicitly.
Preprocessing is fitted on purged training rows only. Earlier yearly Colab
experiments and this single run are distinct; their scores must not be combined
as validation of the saved model.

## Install

Use Python 3.11+ and a dedicated environment, from the repository root:

```bash
python3 -m venv .venv-data
source .venv-data/bin/activate
python -m pip install -r data/requirements.txt -r data/requirements-forecasting.txt
```

The forecasting dependencies are separate from backend production dependencies.
For read-only shared SQL inputs also install `data/requirements-postgres.txt`.

## Inputs and feature contract

Local mode reads `data/artifacts/market/price_only_features.parquet`, when present;
otherwise it explicitly uses the audited equivalent committed
`data/processed/forecast_features.parquet`. Raw prices come from
`data/raw/historical_prices.parquet`, eligibility from `data/asset_universe.csv`.
Pass `--features`, `--prices`, `--universe` to select another matching snapshot.
No dataset is regenerated or overwritten. Sources retain file hashes in reports.

SQL mode reads only `price_only_features`, `historical_prices` and `asset_universe`
in an explicitly pinned, complete snapshot. Credentials use the existing libpq
environment/data `.env` helper; never put passwords in CLI arguments. Reads use
a repeatable read-only transaction. Row counts, columns and snapshot identity
are checked; recorded original-file hashes are provenance, not newly calculated
hashes of SQL row serialization. No schema changes or model upload occur.

The 27 experimental predictors are versioned in `forecasting/inputs.py`:
past returns, rolling RSI/volatility, Bollinger position, return lags, safe volume
changes/ratios, SPY returns, VIX, price-to-moving-average ratios, price-normalized
MACD/ATR, normalized Bollinger width and backward 10-session return. This is
an explicit relative transformation of the prepared allowlist, not a silent
change to `prepare_market_data.py` or the committed numeric schema.

Raw prices validate targets, prices and ten-session outcome dates. RSI edge
semantics are corrected locally: gains with zero losses → 100; no gains/losses
→ 50. Volume change after zero volume remains missing; training-only median
imputation handles it. All remaining predictors must be finite. Missing raw
SPY-calendar sessions are rejected. Identifiers, labels, outcome dates,
training flags and macro/text metadata never enter the estimator.

## Train, select and calibrate

Example using the existing snapshot (all subsequent scores are retrospective):

```bash
python -m data.forecasting train \
  --tuning-start 2025-07-01 \
  --calibration-start 2025-10-01 \
  --evaluation-start 2026-01-01 \
  --as-of 2026-09-18 \
  --model xgboost \
  --output-dir data/artifacts/forecasting/run-2026-09-18
```

An output directory must be new: previous artifacts are never overwritten.
Dates are explicit completed-session dates. `--as-of` is inclusive and censors
outcomes after that date. The four partitions are:

1. Training before tuning start, with outcomes strictly before tuning start.
2. Inner selection from tuning start to calibration start, with outcomes
   strictly before calibration start.
3. Calibration from calibration start to evaluation start, with outcomes
   strictly before evaluation start.
4. Subsequent known outcomes for descriptive evaluation only.

Ticker eligibility requires 252 purged training observations. Calibration
requires at least 30 distinct dates. Learned imputation/scaling use training
only. The estimator selected in step 2 stays frozen for calibration, evaluation
and prediction; inner/calibration/evaluation labels are not added to training.
Refitting later requires new calibration residuals.

For shared SQL inputs, use the same training arguments and add:

```bash
--source postgres --schema ss_ef82d22e57e68952a418 --env-file data/.env
```

That schema is the documented migrated snapshot. The reader verifies its current
metadata instead of assuming that the schema remains usable. The forecasting
reader's live remote permissions/connectivity have not been independently tested.

## Forecast from a saved bundle

```bash
python -m data.forecasting predict \
  --model-dir data/artifacts/forecasting/run-2026-09-18 \
  --as-of 2026-09-18 \
  --output-dir data/artifacts/forecasting/predictions-2026-09-18
```

Only load trusted locally produced bundles. Joblib is executable serialization;
the SHA-256 manifest check detects accidental alteration, not malicious payloads.
New inputs must satisfy the same feature contract. Prediction never fits
preprocessing or recalibrates from new outcomes.

## Outputs and interpretation

Training writes `model.joblib`, `manifest.json`, `report.json`, `forecasts.csv`
under the ignored run directory. Prediction writes reports and forecasts only.
The bundle saves model, fitted preprocessing, allowlist, calibration, boundaries,
eligible tickers, source provenance and library versions. Keep dependency versions
compatible when loading it. Do not commit these generated artifacts or rerun
shared-data migration over them without fixing the separately documented
snapshot-inventory boundary.

Each ticker's latest available completed origin has:

- `predicted_return_10d`: a decimal return (0.01 means +1%).
- `lower_return`, `upper_return`: a nominal 90% interval by default.
- `uncertainty_width_pp`: 100 × (upper − lower), in percentage points.
- `nominal_coverage`: the configured level, **not** measured accuracy.
- Horizon, model identity, origin date, calibration end, generated time and stale
  snapshot flags. Data older than seven calendar days is explicitly stale; this
  is a reporting threshold, not a validated exchange-calendar freshness policy.

Historical volatility scales the width:

```text
scale[t] = max(annualized_volatility_20[t] × sqrt(10/252), 0.005)
score[calibration] = abs(actual_return − prediction) / scale
q = calibration score at rank ceil((n+1) × nominal_coverage)
interval[t] = prediction[t] ± q × scale[t]
```

The calibration report also records a constant-width residual quantile. Serial
dependence, pooled tickers, overlapping labels and market shifts mean that the
usual IID conformal coverage guarantee does not apply. Width expresses
uncertainty, not a probability that the point forecast is correct. Symmetric
return bounds may extend below −100%; they are unbounded statistical intervals,
not price forecasts or personalized investment recommendations.

Reports include MAE/RMSE in percentage points, R², direction/balanced accuracy,
always-up/training-majority accuracy, mean/median return-error benchmarks,
measured interval coverage, mean width and interval score. Already inspected
2025–2026 outcomes cannot be relabeled a fresh test. These retrospective scores
do not establish an advantage or authorize production promotion. Future
prospective checks and fresh, finalized inputs are required for live use.

## Verification

```bash
python -m pytest -q data/tests/test_forecasting_inputs.py \
  data/tests/test_forecasting_sources.py data/tests/test_forecasting_models.py \
  data/tests/test_forecasting_cli.py
```

Tests cover temporal purges, corrected inputs, source immutability, train-only
preprocessing, interval units, SQL read-only behavior, serialization and failures.
They do not download providers, change the database, or exercise backend auth.

### XGBoost local run, 2026-10-08

The saved `xgboost-2026-09-18` run uses the boundaries above. Purged
training/validation/calibration counts are 82,650 / 4,698 / 4,698. Inner validation
selected 10 boosting rounds. All 87 eligible tickers received finite forecasts.
The earlier auto-selection run selected a training-mean baseline and remains a
separate diagnostic artifact.

On 14,703 labeled 2026 evaluation rows, XGBoost MAE was 5.7898 percentage points,
RMSE 8.3787 percentage points and direction accuracy 52.6695%, equal to always-up;
balanced accuracy was 50%. Nominal 90% intervals covered 86.8326% of outcomes,
with mean width 23.9623 percentage points. These are retrospective diagnostics,
not an untouched test or evidence of reliable directional skill. All latest
origins are 2026-09-18 and marked stale.

On this macOS test environment, XGBoost required an existing OpenMP library.
`DYLD_LIBRARY_PATH` was pointed at the temporary scikit-learn environment's
`.dylibs` directory for offline training/tests. The web backend reads CSV/JSON
and does not import XGBoost or require that library.

## Yearly walk-forward retraining

The later authorized stronger experiment runs sequentially with:

```bash
python -m data.forecasting.walkforward \
  --output-dir data/artifacts/forecasting/walkforward-xgboost-2026-09-18
```

Choose a new directory for repeat runs. This command reads the same immutable
local inputs and compares a predeclared grid of 12 XGBoost configurations:
depth/rate pairs (1/.03, 2/.03, 3/.03, 2/.1), each with 10/50/150 rounds.
It tunes in July–September of the preceding year and refits the selected model
on all eligible pre-calibration rows whose outcomes end strictly before October.
Preprocessing is fitted again on those refit rows. October–December remains a
separate calibration period. Evaluation-year labels do not enter selection,
refitting or calibration. Evaluation rows whose outcomes reach the following
year are excluded. Ridge and mean/median baselines use the same dates and their
own calibration residuals. Selection optimizes MAE, not directional accuracy.

Evaluation years are 2024, 2025 and partial 2026. With these windows, 2023 has
only 199 initial training observations per ticker and fails the unchanged
252-observation requirement. No older dataset was rebuilt to include it.

| Evaluation year | XGBoost MAE (pp) | RMSE (pp) | Direction accuracy | Always-UP | 90% interval coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2024 | 4.6856 | 7.1318 | 57.72% | 57.72% | 91.94% |
| 2025 | 5.1035 | 7.2531 | 56.61% | 56.61% | 92.93% |
| 2026 partial | 5.7890 | 8.3530 | 52.67% | 52.67% | 86.93% |

Balanced accuracy is 50% in all three XGBoost folds. Improvements over the
training-median baseline are small; 20-session paired MAE-gain intervals cross
zero in 2025 and 2026. The 2024 positive interval is exploratory and does not
account for prior repeated experiments. Date-block resampling uses 10/20/40
sessions and retains all tickers together on each date. These are retrospective
results, not a new independent test or reliable directional advantage.

The saved latest model uses depth 1, learning rate .03 and 150 rounds selected
on 2025 inner validation. It is refitted through pre-calibration 2025 rows and
calibrated independently. It remains an experimental XGBoost artifact, not a
claim that XGBoost beat every family. Use its directory explicitly to test it;
existing app configuration is not changed automatically.

## Web integration: selected tickers only

The application serves CSV/JSON results, not executable model artifacts. It adds
no training dependencies to the web runtime. Configure the backend process with
an absolute path to a completed export directory:

```dotenv
FORECAST_RESULTS_DIR=/absolute/path/to/data/artifacts/forecasting/walkforward-xgboost-2026-09-18
```

Set this in the local shell or ignored `backend/.env`, then start the backend
and frontend normally. Missing or malformed exports produce a sanitized HTTP 503
and an actionable page error. Recompute/replace results offline using a new run
directory, then point the configuration at that completed run. The application
does not automatically train, refresh or choose another result directory.

Every API request must be authenticated and explicitly name the shortlist:

```text
GET /api/forecasts?tickers=AAPL,NVDA,GEV
```

Only selected available tickers appear in `forecasts`; absent/ineligible selected
tickers appear in `unavailable_tickers`, with no fabricated predictions. Missing,
duplicate or invalid selectors cannot expose the full stored universe. Snapshot
model/calibration metadata and overall historical metrics are shared; metrics
are not recalculated as a claim of accuracy on each user's shortlist.

The content-based recommender can link to:

```text
/forecasts?tickers=AAPL,NVDA,GEV
```

Or call `forecastsService.snapshot(selectedTickers)` from a results component.
The forecasts page never chooses tickers itself. Opening it without a shortlist
shows an empty selection state and sends no forecast request. The current
checkout has onboarding, asset search and a stance rule engine, but no existing
content-based selection endpoint; the teammate's recommender must supply this
list through the documented adapter. Followed tickers are not silently treated
as content recommendations.

The page displays decimal returns as percentages, width in percentage points,
snapshot dates/staleness, nominal versus measured interval coverage and direction
accuracy alongside the always-up benchmark. These remain experimental historical
forecasts rather than buy/sell recommendations. No routes or metadata expose
local artifact paths, source connection settings, or model-pickle contents.

Run isolated backend tests without the database-destructive integration fixtures:

```bash
PYTHONPATH=backend python -m pytest -q --confcutdir=backend/tests/unit backend/tests/unit
```

Then run `npm run lint`, `npx tsc --noEmit` and `npm run build` in `frontend/`.
The full backend integration suite still requires a verified disposable
`stocksense_test` database and must not be aimed at the shared Azure database.
Generated forecast artifacts are not included in the Docker image; deployment
would separately require mounting/provisioning a completed results directory.
No deployment or Docker/CI changes are part of this integration.

### Local web verification

Fourteen isolated backend tests and eight subtests pass, including real JWT
authentication against stubbed repositories, inactive-user rejection, required
selection, malformed exports and missing-configuration handling. No application
database was connected or dropped. An additional local API check used the actual
87-asset export: `AAPL,NVDA,GEV` returned only AAPL/NVDA and marked GEV unavailable.
Frontend lint and TypeScript checks pass. The production build passes with
`npx next build --webpack`; the default Turbopack build was blocked by this
execution environment's subprocess port-binding restriction. No browser visual
check or full application-database integration test was performed.

## Database-free local preview

For the explicitly authorized temporary UI preview, run from `backend/`:

```bash
python -m app.forecast_demo
```

Open http://127.0.0.1:8001. This separate standard-library server binds only to
loopback, reads the saved walk-forward XGBoost CSV/JSON export, and uses manual
ticker selection. It has no user accounts, login or database. It is not included
in `app.main`, Docker startup or the Next.js app. It must not be used as a
production endpoint or as evidence that database-backed login has been tested.
Stop it with Ctrl+C. Browser checks verified AAPL/NVDA display, unavailable GEV
coverage and invalid-ticker errors. The authenticated application is unchanged.
