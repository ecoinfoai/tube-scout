"""Tests for auth.py OAuth-only authentication (US1).

idea6 ADR-IDEA6-004: ``_default_client_secret_path`` is now a thin
delegate to ``services.secret_loader.resolve_client_secret_path``,
which raises :class:`SecretConfigError` (a subclass of
:class:`UserFacingError`) instead of bare ``ValueError``/
``FileNotFoundError``. The tests below pin the new contract while
covering the same edge cases.
"""

from pathlib import Path

import pytest

from tube_scout.cli.errors import UserFacingError
from tube_scout.services.auth import _default_client_secret_path


@pytest.fixture(autouse=True)
def _isolate_b64(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TUBE_SCOUT_CLIENT_SECRET_B64", raising=False)


class TestDefaultClientSecretPath:
    """Tests for _default_client_secret_path — delegates to secret_loader."""

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
        """SecretConfigError when neither path nor _B64 form is set."""
        monkeypatch.delenv("TUBE_SCOUT_CLIENT_SECRET", raising=False)

        with pytest.raises(UserFacingError, match="TUBE_SCOUT_CLIENT_SECRET"):
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

        with pytest.raises(UserFacingError, match="TUBE_SCOUT_CLIENT_SECRET"):
            _default_client_secret_path()

    def test_raises_when_env_var_file_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SecretConfigError when env var points to a missing file."""
        monkeypatch.setenv(
            "TUBE_SCOUT_CLIENT_SECRET", "/nonexistent/client_secret.json"
        )

        with pytest.raises(UserFacingError, match="does not exist"):
            _default_client_secret_path()
