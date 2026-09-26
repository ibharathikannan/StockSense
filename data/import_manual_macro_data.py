#!/usr/bin/env python3
"""Combine manually downloaded FRED CSV files into the macro dataset."""

from pathlib import Path

import pandas as pd


DATA_DIR = Path(__file__).resolve().parent
INPUT_DIR = DATA_DIR / "raw" / "manual_macro"
OUTPUT_DIR = DATA_DIR / "raw"

SERIES_CONFIG = {
    "DFF": {
        "name": "Federal Funds Rate",
        "frequency": "daily",
        "availability_days": 1,
    },
    "CPIAUCSL": {
        "name": "Consumer Price Index",
        "frequency": "monthly",
        # Manual FRED CSVs contain observation dates but not release dates.
        # Fifty days is a conservative proxy for the following month's release.
        "availability_days": 50,
    },
    "DGS10": {
        "name": "10-Year Treasury Yield",
        "frequency": "daily",
        "availability_days": 1,
    },
    "VIXCLS": {
        "name": "VIX",
        "frequency": "daily",
        "availability_days": 0,
    },
}


def load_series(input_dir: Path, series_id: str) -> pd.DataFrame:
    """Load and validate one two-column FRED website download."""
    config = SERIES_CONFIG[series_id]
    path = input_dir / f"{series_id}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing manual FRED download: {path}")

    df = pd.read_csv(path)
    expected_columns = ["observation_date", series_id]
    if df.columns.tolist() != expected_columns:
        raise ValueError(
            f"{path} must have columns {expected_columns}; found {df.columns.tolist()}"
        )

    df = df.rename(columns={series_id: "value"})
    df["observation_date"] = pd.to_datetime(
        df["observation_date"], errors="raise"
    )
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    if df["observation_date"].duplicated().any():
        raise ValueError(f"{path} contains duplicate observation dates")
    if not df["observation_date"].is_monotonic_increasing:
        raise ValueError(f"{path} must be sorted by observation_date")

    # Holiday blanks carry no new daily information. Keep CPI blanks because a
    # missing month is meaningful and preserves correct 12-month alignment.
    if series_id != "CPIAUCSL":
        df = df.dropna(subset=["value"])

    df["available_date"] = df["observation_date"] + pd.to_timedelta(
        config["availability_days"], unit="D"
    )
    df["realtime_end"] = pd.NaT
    df.insert(0, "series_id", series_id)
    df.insert(1, "series_name", config["name"])
    df.insert(2, "frequency", config["frequency"])
    return df[
        [
            "series_id",
            "series_name",
            "frequency",
            "observation_date",
            "value",
            "available_date",
            "realtime_end",
        ]
    ]


def build_manual_macro_dataset(input_dir: Path = INPUT_DIR) -> pd.DataFrame:
    """Combine all required manual downloads using the pipeline schema."""
    frames = [load_series(input_dir, series_id) for series_id in SERIES_CONFIG]
    return (
        pd.concat(frames, ignore_index=True)
        .sort_values(["series_id", "observation_date"])
        .reset_index(drop=True)
    )


def main() -> None:
    macro_data = build_manual_macro_dataset()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / "macro_indicators.csv"
    parquet_path = OUTPUT_DIR / "macro_indicators.parquet"

    macro_data.to_csv(csv_path, index=False, date_format="%Y-%m-%d")
    macro_data.to_parquet(parquet_path, engine="pyarrow", index=False)

    print(f"CSV saved: {csv_path}")
    print(f"Parquet saved: {parquet_path}")
    print(f"Rows: {len(macro_data):,}")
    for series_id, group in macro_data.groupby("series_id", sort=False):
        missing = int(group["value"].isna().sum())
        print(
            f"  {series_id}: {len(group):,} rows, "
            f"{group['observation_date'].min().date()} to "
            f"{group['observation_date'].max().date()}, "
            f"{missing} missing value(s)"
        )


if __name__ == "__main__":
    main()
