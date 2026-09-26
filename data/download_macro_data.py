#!/usr/bin/env python3
"""Download raw macroeconomic observations from the FRED API."""

from datetime import date, timedelta
import json
import os
from pathlib import Path
import ssl
import time
from urllib.error import HTTPError
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
REQUEST_INTERVAL_SECONDS = 1.0
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 60.0
REQUEST_TIMEOUT_SECONDS = 60

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


def date_ranges(start: str, end: str, frequency: str) -> list[tuple[str, str]]:
    """Create inclusive request ranges from an inclusive/exclusive date range.

    Initial-release queries cover many real-time vintages and are expensive for
    FRED to compute. Calendar-quarter ranges keep each response reliable. The
    caller paces them to remain below FRED's request-rate limit.
    """
    del frequency  # Both daily and monthly vintage queries need small windows.
    current = date.fromisoformat(start)
    final_date = date.fromisoformat(end) - timedelta(days=1)
    if final_date < current:
        return []

    ranges = []
    while current <= final_date:
        quarter_end_month = ((current.month - 1) // 3 + 1) * 3
        if quarter_end_month == 12:
            calendar_quarter_end = date(current.year, 12, 31)
        else:
            calendar_quarter_end = (
                date(current.year, quarter_end_month + 1, 1) - timedelta(days=1)
            )
        chunk_end = min(calendar_quarter_end, final_date)
        ranges.append((current.isoformat(), chunk_end.isoformat()))
        current = chunk_end + timedelta(days=1)

    return ranges


def retry_delay(error: Exception, attempt: int) -> float:
    """Return FRED's requested cooldown, or a conservative fallback delay."""
    if isinstance(error, HTTPError) and error.code == 429:
        retry_after = error.headers.get("Retry-After") if error.headers else None
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
        return DEFAULT_RATE_LIMIT_WAIT_SECONDS

    return float(2 ** (attempt - 1))


def download_series_chunk(
    series_id: str,
    api_key: str,
    observation_start: str,
    observation_end: str,
) -> list[dict]:
    """Download one chunk of initial-release observations."""
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
                timeout=REQUEST_TIMEOUT_SECONDS,
                context=FRED_SSL_CONTEXT,
            ) as response:
                observations = json.load(response).get("observations", [])

            return observations

        except Exception as error:
            last_error = error
            delay = retry_delay(error, attempt)
            print(
                f"  {observation_start} to {observation_end}, "
                f"attempt {attempt}/{MAX_ATTEMPTS} failed: {error}"
            )
            if attempt < MAX_ATTEMPTS:
                print(f"  Retrying in {delay:g} seconds...")
                time.sleep(delay)

    raise RuntimeError(last_error)


def download_one_series(series_id: str, api_key: str) -> pd.DataFrame:
    """Download initial releases in a small number of safe chunks."""
    observations = []
    _, frequency = FRED_SERIES[series_id]
    request_ranges = date_ranges(START_DATE, END_DATE, frequency)

    for position, (chunk_start, chunk_end) in enumerate(request_ranges, start=1):
        print(
            f"  Fetching period {position}/{len(request_ranges)}: "
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
        time.sleep(REQUEST_INTERVAL_SECONDS)

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
    if len(api_key) != 32 or not api_key.isalnum() or not api_key.islower():
        raise ValueError(
            "FRED_API_KEY must be the 32-character lowercase key from your "
            "FRED account."
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
