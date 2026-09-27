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
