#!/usr/bin/env python3
"""Convert StockSense Parquet datasets into local CSV copies."""

import argparse
from pathlib import Path

import pandas as pd


DATA_DIR = Path(__file__).resolve().parent
DEFAULT_DIRECTORIES = [DATA_DIR / "raw", DATA_DIR / "processed"]


def find_parquet_files() -> list[Path]:
    """Find every standard StockSense Parquet dataset."""
    return sorted(
        path
        for directory in DEFAULT_DIRECTORIES
        for path in directory.glob("*.parquet")
    )


def convert_parquet_to_csv(parquet_path: Path) -> Path:
    """Write a CSV beside one Parquet file and return the CSV path."""
    if not parquet_path.is_file():
        raise FileNotFoundError(f"Parquet file not found: {parquet_path}")
    if parquet_path.suffix.lower() != ".parquet":
        raise ValueError(f"Expected a .parquet file: {parquet_path}")

    csv_path = parquet_path.with_suffix(".csv")
    dataframe = pd.read_parquet(parquet_path)
    dataframe.to_csv(csv_path, index=False, date_format="%Y-%m-%d")

    print(
        f"Converted {parquet_path} -> {csv_path} "
        f"({len(dataframe):,} rows)"
    )
    return csv_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert Parquet datasets to CSV. With no file arguments, all "
            "Parquet files in data/raw and data/processed are converted."
        )
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Optional specific .parquet files to convert.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    parquet_files = args.files or find_parquet_files()

    if not parquet_files:
        raise FileNotFoundError(
            "No Parquet datasets were found in data/raw or data/processed."
        )

    for parquet_path in parquet_files:
        convert_parquet_to_csv(parquet_path)


if __name__ == "__main__":
    main()
