#!/usr/bin/env python3
"""Download raw macroeconomic observations from the FRED API."""

from datetime import date, timedelta
import json
import os
from pathlib import Path
import ssl
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi
import pandas as pd


# --------------------------------------------------
# 1. Configuration
# --------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = DATA_DIR / "raw"

START_DATE = "2020-09-01"
END_DATE = date.today().isoformat()
MAX_ATTEMPTS = 3
RELEASE_BUFFER_DAYS = 120

# Some standalone macOS Python installations do not have a usable default CA
# file. certifi supplies a maintained CA bundle while keeping SSL verification
# fully enabled.
FRED_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

FRED_SERIES = {
    "DFF": ("Federal Funds Rate", "daily"),
    "CPIAUCSL": ("Consumer Price Index", "monthly"),
    "DGS10": ("10-Year Treasury Yield", "daily"),
    "VIXCLS": ("VIX", "daily"),
}


def yearly_date_ranges(start: str, end: str) -> list[tuple[str, str]]:
    """Split an inclusive/exclusive date range into inclusive calendar years."""
    current = date.fromisoformat(start)
    final_date = date.fromisoformat(end) - timedelta(days=1)
    ranges = []

    while current <= final_date:
        chunk_end = min(date(current.year, 12, 31), final_date)
        ranges.append((current.isoformat(), chunk_end.isoformat()))
        current = chunk_end + timedelta(days=1)

    return ranges


def download_series_chunk(
    series_id: str,
    api_key: str,
    observation_start: str,
    observation_end: str,
) -> list[dict]:
    """Download one calendar-year chunk of initial-release observations."""
    # An observation's first publication occurs after its observation date.
    # These series are daily or monthly, so 120 days safely includes that first
    # release without asking FRED to scan centuries of unrelated vintages.
    realtime_start = observation_start
    realtime_end = min(
        date.fromisoformat(observation_end) + timedelta(days=RELEASE_BUFFER_DAYS),
        date.fromisoformat(END_DATE),
    ).isoformat()

    parameters = urlencode(
        {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": observation_start,
            "observation_end": observation_end,
            "realtime_start": realtime_start,
            "realtime_end": realtime_end,
            # Initial releases avoid using later revisions in old model rows.
            "output_type": 4,
        }
    )
    url = f"https://api.stlouisfed.org/fred/series/observations?{parameters}"
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            request = Request(
                url,
                headers={"User-Agent": "StockSense academic project"},
            )
            with urlopen(
                request,
                timeout=30,
                context=FRED_SSL_CONTEXT,
            ) as response:
                observations = json.load(response).get("observations", [])

            return observations

        except Exception as error:
            last_error = error
            print(
                f"  {observation_start} to {observation_end}, "
                f"attempt {attempt}/{MAX_ATTEMPTS} failed: {error}"
            )
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 ** (attempt - 1))

    raise RuntimeError(last_error)


def download_one_series(series_id: str, api_key: str) -> pd.DataFrame:
    """Download initial releases in small chunks and combine them."""
    observations = []
    date_ranges = yearly_date_ranges(START_DATE, END_DATE)

    for position, (chunk_start, chunk_end) in enumerate(date_ranges, start=1):
        print(
            f"  Fetching period {position}/{len(date_ranges)}: "
            f"{chunk_start} to {chunk_end}"
        )
        observations.extend(
            download_series_chunk(
                series_id,
                api_key,
                chunk_start,
                chunk_end,
            )
        )

    if not observations:
        raise ValueError("no observations returned")

    series_name, frequency = FRED_SERIES[series_id]
    df = pd.DataFrame(observations)[
        ["date", "value", "realtime_start", "realtime_end"]
    ]
    df = df.rename(
        columns={
            "date": "observation_date",
            "realtime_start": "available_date",
        }
    )
    df["observation_date"] = pd.to_datetime(df["observation_date"])
    df["available_date"] = pd.to_datetime(df["available_date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df.insert(0, "series_id", series_id)
    df.insert(1, "series_name", series_name)
    df.insert(2, "frequency", frequency)

    return (
        df.dropna(subset=["value"])
        .drop_duplicates(subset=["observation_date", "available_date"], keep="last")
        .sort_values(["observation_date", "available_date"])
        .reset_index(drop=True)
    )


def main() -> None:
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "FRED_API_KEY is not set. Create a FRED API key and export it first."
        )

    all_series = []
    failed_series = []

    for series_id, (series_name, _) in FRED_SERIES.items():
        print(f"Downloading {series_id} ({series_name})...")
        try:
            df = download_one_series(series_id, api_key)
            all_series.append(df)
            print(f"  Downloaded {len(df):,} observations.")
        except Exception as error:
            failed_series.append(series_id)
            print(f"  Failed for {series_id}: {error}")

    if not all_series:
        raise ValueError("No FRED data was downloaded.")

    macro_data = pd.concat(all_series, ignore_index=True)
    macro_data = macro_data.sort_values(
        ["series_id", "observation_date", "available_date"]
    ).reset_index(drop=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / "macro_indicators.csv"
    parquet_path = OUTPUT_DIR / "macro_indicators.parquet"

    macro_data.to_csv(csv_path, index=False, date_format="%Y-%m-%d")
    print(f"\nCSV saved: {csv_path}")

    try:
        macro_data.to_parquet(parquet_path, engine="pyarrow", index=False)
        print(f"Parquet saved: {parquet_path}")
    except Exception as error:
        print("Parquet export failed, but the CSV was saved successfully.")
        print(f"Parquet error: {error}")

    if failed_series:
        print(f"Failed series: {', '.join(failed_series)}")
    else:
        print("All requested FRED series downloaded successfully.")


if __name__ == "__main__":
    main()
