"""Tests for JSON store read/write operations."""

from pathlib import Path

import pytest

from tube_scout.storage.json_store import read_json, write_json


class TestJsonStore:
    """Tests for JSON store functions."""

    def test_write_and_read_round_trip(self, tmp_path: Path) -> None:
        filepath = tmp_path / "test.json"
        data = {"key": "value", "number": 42, "list": [1, 2, 3]}
        write_json(filepath, data)
        result = read_json(filepath)
        assert result == data

    def test_read_nonexistent_file_returns_none(self, tmp_path: Path) -> None:
        filepath = tmp_path / "nonexistent.json"
        result = read_json(filepath)
        assert result is None

    def test_atomic_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        filepath = tmp_path / "nested" / "dir" / "test.json"
        data = {"key": "value"}
        write_json(filepath, data)
        assert filepath.exists()
        assert read_json(filepath) == data

    def test_atomic_write_no_partial_on_error(self, tmp_path: Path) -> None:
        filepath = tmp_path / "test.json"
        data = {"initial": "data"}
        write_json(filepath, data)

        # Writing circular reference should fail without corrupting existing file
        circular: dict = {}
        circular["self"] = circular
        with pytest.raises(ValueError):
            write_json(filepath, circular)

        # Original file should still be intact
        assert read_json(filepath) == data

    def test_write_nested_data(self, tmp_path: Path) -> None:
        filepath = tmp_path / "nested.json"
        data = {
            "channels": [
                {"channel_id": "UC123", "professor_name": "Prof"},
            ],
            "settings": {"data_dir": "./data"},
        }
        write_json(filepath, data)
        result = read_json(filepath)
        assert result == data

    def test_write_overwrites_existing(self, tmp_path: Path) -> None:
        filepath = tmp_path / "test.json"
        write_json(filepath, {"old": "data"})
        write_json(filepath, {"new": "data"})
        result = read_json(filepath)
        assert result == {"new": "data"}
