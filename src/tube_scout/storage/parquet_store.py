"""Parquet file read/write using polars."""

from pathlib import Path

import polars as pl


def read_parquet(filepath: Path) -> pl.DataFrame | None:
    """Read a Parquet file into a polars DataFrame.

    Args:
        filepath: Path to the Parquet file.

    Returns:
        DataFrame, or None if file does not exist.
    """
    if not filepath.exists():
        return None
    return pl.read_parquet(filepath)


def write_parquet(filepath: Path, df: pl.DataFrame) -> None:
    """Write a polars DataFrame to Parquet.

    Args:
        filepath: Path to the output Parquet file.
        df: DataFrame to write.
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(filepath)


def append_parquet(filepath: Path, df: pl.DataFrame) -> None:
    """Append a DataFrame to an existing Parquet file.

    If the file does not exist, creates a new one.

    Args:
        filepath: Path to the Parquet file.
        df: DataFrame to append.
    """
    existing = read_parquet(filepath)
    if existing is not None:
        combined = pl.concat([existing, df])
    else:
        combined = df
    write_parquet(filepath, combined)
