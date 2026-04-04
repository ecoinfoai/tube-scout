"""Unit tests for get_device() configuration function."""


import pytest

from tube_scout.models.config import get_device


class TestGetDevice:
    """Tests for get_device() env var reading and validation."""

    def test_returns_cpu_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default to 'cpu' when TUBE_SCOUT_DEVICE is not set."""
        monkeypatch.delenv("TUBE_SCOUT_DEVICE", raising=False)
        assert get_device() == "cpu"

    def test_returns_cuda_when_set_to_cuda(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Return 'cuda' when TUBE_SCOUT_DEVICE=cuda."""
        monkeypatch.setenv("TUBE_SCOUT_DEVICE", "cuda")
        assert get_device() == "cuda"

    def test_returns_cpu_when_set_to_cpu(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Return 'cpu' when TUBE_SCOUT_DEVICE=cpu."""
        monkeypatch.setenv("TUBE_SCOUT_DEVICE", "cpu")
        assert get_device() == "cpu"

    def test_raises_for_invalid_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raise ValueError for invalid TUBE_SCOUT_DEVICE values."""
        monkeypatch.setenv("TUBE_SCOUT_DEVICE", "tpu")
        with pytest.raises(ValueError, match="TUBE_SCOUT_DEVICE must be"):
            get_device()

    def test_raises_for_empty_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Raise ValueError for empty TUBE_SCOUT_DEVICE."""
        monkeypatch.setenv("TUBE_SCOUT_DEVICE", "")
        with pytest.raises(ValueError, match="TUBE_SCOUT_DEVICE must be"):
            get_device()

    def test_case_sensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TUBE_SCOUT_DEVICE should be case-sensitive (CUDA is invalid)."""
        monkeypatch.setenv("TUBE_SCOUT_DEVICE", "CUDA")
        with pytest.raises(ValueError, match="TUBE_SCOUT_DEVICE must be"):
            get_device()
