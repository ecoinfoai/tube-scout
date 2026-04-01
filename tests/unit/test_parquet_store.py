"""Tests for Parquet store read/write operations."""

from pathlib import Path

import polars as pl

from tube_scout.storage.parquet_store import (
    append_parquet,
    read_parquet,
    write_parquet,
)


class TestParquetStore:
    """Tests for Parquet store functions."""

    def test_write_and_read_round_trip(self, tmp_path: Path) -> None:
        filepath = tmp_path / "test.parquet"
        df = pl.DataFrame({"id": ["a", "b"], "value": [1, 2]})
        write_parquet(filepath, df)
        result = read_parquet(filepath)
        assert result.shape == (2, 2)
        assert result["id"].to_list() == ["a", "b"]
        assert result["value"].to_list() == [1, 2]

    def test_read_nonexistent_returns_none(self, tmp_path: Path) -> None:
        filepath = tmp_path / "nonexistent.parquet"
        result = read_parquet(filepath)
        assert result is None

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        filepath = tmp_path / "nested" / "dir" / "test.parquet"
        df = pl.DataFrame({"col": [1, 2, 3]})
        write_parquet(filepath, df)
        assert filepath.exists()

    def test_append_to_existing(self, tmp_path: Path) -> None:
        filepath = tmp_path / "test.parquet"
        df1 = pl.DataFrame({"id": ["a"], "value": [1]})
        df2 = pl.DataFrame({"id": ["b"], "value": [2]})
        write_parquet(filepath, df1)
        append_parquet(filepath, df2)
        result = read_parquet(filepath)
        assert result.shape == (2, 2)
        assert result["id"].to_list() == ["a", "b"]

    def test_append_to_nonexistent_creates_new(self, tmp_path: Path) -> None:
        filepath = tmp_path / "new.parquet"
        df = pl.DataFrame({"id": ["a"], "value": [1]})
        append_parquet(filepath, df)
        result = read_parquet(filepath)
        assert result.shape == (1, 2)
