"""Tests for auth.py OAuth-only authentication (US1)."""

from pathlib import Path

import pytest

from tube_scout.services.auth import _default_client_secret_path


class TestDefaultClientSecretPath:
    """Tests for _default_client_secret_path — env var only, no file-glob."""

    def test_returns_path_from_env_var(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Should return path from TUBE_SCOUT_CLIENT_SECRET env var."""
        secret_file = tmp_path / "client_secret.json"
        secret_file.write_text("{}")
        monkeypatch.setenv("TUBE_SCOUT_CLIENT_SECRET", str(secret_file))

        result = _default_client_secret_path()
        assert result == secret_file

    def test_raises_when_env_var_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should raise ValueError when TUBE_SCOUT_CLIENT_SECRET is not set."""
        monkeypatch.delenv("TUBE_SCOUT_CLIENT_SECRET", raising=False)

        with pytest.raises(ValueError, match="TUBE_SCOUT_CLIENT_SECRET"):
            _default_client_secret_path()

    def test_no_file_glob_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Should NOT fall back to file-glob in ~/.config/tube-scout/."""
        monkeypatch.delenv("TUBE_SCOUT_CLIENT_SECRET", raising=False)
        # Even if a client_secret file exists in config dir, it should not be found
        config_dir = tmp_path / ".config" / "tube-scout"
        config_dir.mkdir(parents=True)
        (config_dir / "client_secret_12345.json").write_text("{}")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        with pytest.raises(ValueError, match="TUBE_SCOUT_CLIENT_SECRET"):
            _default_client_secret_path()

    def test_raises_when_env_var_file_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should raise FileNotFoundError when env var points to missing file."""
        monkeypatch.setenv(
            "TUBE_SCOUT_CLIENT_SECRET", "/nonexistent/client_secret.json"
        )

        with pytest.raises(FileNotFoundError, match="not found"):
            _default_client_secret_path()
