# StockSense data pipeline

Each step has its own script so that price collection, macro collection, and
feature engineering can be run and understood independently.

```text
asset_universe.csv
        |
        v
download_historical_prices.py ---> data/raw/historical_prices.*
                                             |
download_macro_data.py ----------> data/raw/macro_indicators.*
                                             |
                                             v
                                  build_features.py
                                             |
                                             v
                              data/processed/forecast_features.*
```

The shared universe contains **80 stocks, 10 ETFs, and VIX as a context-only
index**. `FPS`, `GEV`, and `CEG` are useful recommendation assets, but are marked
`forecast_eligible=false` because they do not have a full five-year independent
trading history.

## 1. Install the data dependencies

Run this once from the repository root. Package installation commands do not
belong inside the Python scripts.

```bash
python3 -m venv .venv-data
source .venv-data/bin/activate
python3 -m pip install -r data/requirements.txt
```

In a Jupyter notebook, `%pip install ...` is notebook syntax. These repository
files are normal `.py` scripts, so their dependencies are listed in
`data/requirements.txt` instead.

## 2. Download historical prices

```bash
python3 data/download_historical_prices.py
```

This script does only one job: it downloads daily Yahoo Finance data and writes:

- `data/raw/historical_prices.csv`
- `data/raw/historical_prices.parquet`

Parquet is the shared, version-controlled dataset. The CSV is a local convenience
copy and is ignored by Git.

The columns stay close to the original script: `Date`, `ticker`, `Open`, `High`,
`Low`, `Close`, `Adj Close`, `Volume`, `Dividends`, and `Stock Splits`.

The raw download begins one year before the model period so that SMA-200 and
other rolling indicators can warm up. The feature script keeps model rows from
2021-09-01 onward.

## 3. Download FRED macro data

Create a free FRED API key, place it in your terminal environment, and run the
macro downloader separately:

```bash
export FRED_API_KEY="your-fred-api-key"
python3 data/download_macro_data.py
```

It writes `data/raw/macro_indicators.csv` and `.parquet` with the Parquet file
used as the shared, version-controlled copy:

- Federal Funds Rate (`DFF`)
- Consumer Price Index (`CPIAUCSL`)
- 10-Year Treasury Yield (`DGS10`)
- VIX (`VIXCLS`)

Initial published FRED values and their availability dates are retained so that
historical model evaluation does not accidentally use later revisions.

If the API is unavailable, download the four series as CSV from their FRED pages
into `data/raw/manual_macro/`, using the series IDs as filenames, then run:

```bash
python3 data/import_manual_macro_data.py
```

Website CSV exports contain revised values and observation dates, not historical
release metadata. The manual importer therefore applies conservative availability
lags before writing the same `macro_indicators.*` schema. It preserves genuinely
missing monthly CPI observations and removes expected daily market-holiday blanks.

## 4. Build forecasting features

```bash
python3 data/build_features.py
```

This reads the raw files and writes:

- `data/processed/forecast_features.csv`
- `data/processed/forecast_features.parquet`

The Parquet feature file is committed. The large CSV copy stays local.

The feature dataset includes:

- 1-, 5-, and 20-day returns and log returns
- SMA-5/20/50/200 and EMA-12/26
- RSI-14, MACD, ATR-14, and 20-day annualised volatility
- Bollinger Bands
- price, return, and volume lag features
- SPY market returns and VIX context
- asset type, category, and sector from `asset_universe.csv`
- FRED rate, inflation, Treasury-yield, and VIX context when available
- `target_return_10d`, the label predicted by the models
- `is_training_row`, which is false for the latest rows whose future target is
  not known yet but which can still be used for inference

Fit scalers and other learned preprocessing only on each training fold during
walk-forward validation. Do not randomly split this time-series dataset.

## 5. Convert Parquet datasets to CSV

After cloning the repository, convert every shared dataset to CSV with:

```bash
python3 data/convert_parquet_to_csv.py
```

To convert only one dataset:

```bash
python3 data/convert_parquet_to_csv.py data/raw/historical_prices.parquet
```

The CSV is written beside the Parquet file with the same base name. Existing
CSV copies are replaced so they always match the shared Parquet data.

Yahoo Finance data obtained through `yfinance` is intended for research and
personal use. Review the provider's terms before redistributing it.

## 6. Collection and preparation worktree

The AI worktree adds offline collection and preparation commands. The current
authorization ends after preparation: the independent data-readiness gate,
forecast-model training, retrieval indexes, RAG generation, and rule-engine
integration have not started. Agent ownership and the handoff live in
[`docs/ai/PLAN.md`](../docs/ai/PLAN.md).

New corpora and candidate datasets go under ignored `data/artifacts/`; model
caches and the Alpha Vantage quota ledger go under ignored `data/.cache/`.
The committed price, macro, feature, and asset-profile artifacts are not
overwritten by these commands. Keep downloaded provider content local; API
access alone does not establish public redistribution rights.

### Configure collection

```bash
cp data/.env.example data/.env
```

Fill **`data/.env`**, not the example file, with `APCA_API_KEY_ID`,
`APCA_API_SECRET_KEY`, and `ALPHA_VANTAGE_API_KEY`. Exported environment
variables take precedence. Values are read literally without shell expansion.

SEC EDGAR needs no API key. Set `SEC_USER_AGENT` to an organization/project
name followed by a real contact email. Collection waits for this identification
instead of guessing one. Secrets must never be committed or pasted into logs.

### Audit and prepare market candidates

```bash
python3 data/prepare_market_data.py
```

This writes price-only and macro-enriched feature Parquets plus a manifest in
`data/artifacts/market/`. The manifest records source hashes, coverage,
missingness, target checks, predictor allowlists, and macro provenance. It is
a descriptive preparation report, not a readiness or model-promotion decision.

The current committed feature table matches the price-only candidate. The
macro artifact's fixed availability lags and null vintage-end fields match
the manual-import format, so historical point-in-time values remain unverified.
The macro candidate must not silently become the default training dataset.

### Collect SEC filings

```bash
python3 data/collect_sec_filings.py --pilot 5
python3 data/collect_sec_filings.py
```

The first command is the parsing/issuer-mapping pilot. After inspecting its
outputs, the second collects all stock issuers and records ETFs/VIX as not
applicable to this corporate-filing corpus. Defaults are two annual reports,
four domestic quarterly reports, and 90 days of event filings. Foreign issuers
use 20-F or Canadian 40-F annual reports and recent 6-K forms. Missing history is recorded explicitly.

`data/artifacts/sec/` contains `documents.jsonl`, per-ticker `coverage.json`,
and raw cached responses/documents. Hidden XBRL metadata is excluded from text;
visible facts and table cell boundaries are preserved. Parser version changes
refresh normalized text from cached HTML while preserving fetch timestamps.
Every record retains acceptance time,
accession, form, issuer, source URL, and content hash. Inventories refresh once
per run; accession documents are reused. Earlier historical cutoffs require
a separate output directory if a later snapshot already exists.

Use `--tickers AAPL,MSFT`, `--as-of 2026-10-02T00:00:00Z`, or
`--output-dir data/artifacts/sec-pilot` for bounded runs. Requests are throttled
to two per second, with retries for transient failures.

### Collect recent news

```bash
python3 data/collect_news.py --provider alpaca --days 1
python3 data/collect_news.py --provider alpaca --days 30
python3 data/collect_news.py --provider alpha_vantage --days 7
```

Alpaca is the primary corpus: every result page is fetched, then provider ticker
tags are matched against all 90 stocks/ETFs. The cutoff defaults to 15 minutes
before the current time. Daily windows resume independently; failed windows
are retried rather than marked complete. Article revisions are retained.

Alpha Vantage is supplementary. Its 25-request UTC-day budget is reserved
atomically before each request, including retries, and is shared across output
directories. Do not delete its quota database to reset usage; calls made outside
these collectors still count toward the provider's quota. Newest windows are
requested first. A 1,000-item response is marked partial, and provider notices
stop the run instead of consuming the remaining budget. Partial supplementation
does not establish complete historical news coverage.

`data/artifacts/news/` contains `documents.jsonl` and `coverage.json` with
window outcomes and ticker counts. News `available_at` is the first time that
version was collected, not its original publication time. Provider sentiment
stays separate from locally inferred sentiment. Missing sentiment stays missing.

### Prepare text and local sentiment

Install the optional offline preparation dependencies in the data environment:

```bash
python3 -m pip install -r data/requirements-preparation.txt
python3 data/prepare_text_data.py --download-models
```

The first preparation run downloads pinned public tokenizer/FinBERT revisions
to `data/.cache/huggingface/`. Subsequent runs work from local weights:

```bash
python3 data/prepare_text_data.py
```

Outputs under `data/artifacts/prepared/` are:

- `documents.jsonl`: normalized current document versions with source provenance.
- `chunks.jsonl`: section-aware, 220-token passages with 32-token overlap;
  character offsets refer to the normalized document text and retain source URLs.
- `sentiment.jsonl`: per-article/ticker pretrained FinBERT estimates, attribution
  gaps, truncation indicators, and the pinned model revision.
- `sentiment_aggregates.jsonl`: current seven-day ticker aggregates with a two-day
  decay half-life; local estimates and Alpha Vantage scores remain separate.
- `manifest.json`: source hashes, coverage, rejected records, and preparation counts.

Only company-specific sentences are scored; sentences that mention multiple
tagged companies are excluded from per-company attribution. This is a
conservative heuristic, not an independently validated sentiment benchmark.
No local sentiment score is manufactured when attribution is unavailable.
Use `--sentiment none` to explicitly skip scoring; the manifest records the skip.

`--as-of` filters by known availability and revision time. Current/backfilled
news snapshots are not automatically valid historical training features.
SEC/source gaps remain visible in the manifest. This stage performs no PCA,
forecast training, embedding generation, vector indexing, or LLM generation.

### Implementation checks

```bash
python3 -m pytest -q data/tests
```

These tests use temporary fixture data and mocked provider requests. They do
not access MongoDB, consume API quota, or run the independent data gate.

## 7. Shared data: Azure PostgreSQL

Import canonical Parquet datasets into numeric SQL tables, and prepared SEC/news
documents and chunks into text tables with source metadata and complete JSONB
payloads. The importer also archives original inventoried files by default.
See [`SHARED_DATA.md`](SHARED_DATA.md) for connection configuration and examples.
MongoDB remains the web application's database.

Inventory is read-only and makes no network requests:

```bash
python3 -m data.shared_data inventory --source-root data
```

Install the optional PostgreSQL dependency separately, then import and verify
using local libpq connection settings:

```bash
python3 -m pip install -r data/requirements-postgres.txt
python3 -m data.shared_data postgres-import --source-root data --prompt-password
python3 -m data.shared_data postgres-verify --source-root data --prompt-password
```

The importer preserves immutable snapshots and can resume incomplete uploads.
Keep original files and committed baselines until verification succeeds. CSV
convenience copies are redundant and excluded; the asset universe CSV is imported.
Embeddings, vector indexes and RAG generation are not implemented by these
commands.
