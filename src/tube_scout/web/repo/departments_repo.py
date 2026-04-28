"""Departments registry repository (T022).

Persists the operator-managed mapping of alias → display name + agenix env
names in ``departments.json`` under ``CONFIG_DIR``.

Persistence guarantees:
- **Atomic write**: writes a sibling ``.tmp`` file then ``os.replace()``
  (POSIX rename guarantee). A crash between tmp-write and rename leaves the
  original file intact (T007 ``test_atomic_write_no_partial_file_on_crash``).
- **mtime-based cache**: subsequent ``list_all()`` calls skip JSON parse when
  the file's mtime has not changed; an external rewrite (operator manually
  editing the file) is observed without a process restart (FR-025).
- **Pydantic validation**: each row goes through :class:`models.Department`
  so the alias / env-var regex rules are enforced at load and write.

Module-level ``os`` and ``json`` are imported as plain names so tests can
monkeypatch them (T007 atomic-write fixture replaces ``os.replace``).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from tube_scout.web.models import Department
from tube_scout.web.paths import get_config_dir

_FILENAME = "departments.json"


class DuplicateAliasError(ValueError):
    """Raised when the operator attempts to add a duplicate alias."""


class DepartmentsRepo:
    """Read/write the ``departments.json`` registry.

    The instance maintains an in-memory cache keyed by file mtime; multiple
    repo instances are safe because each one re-checks the on-disk mtime
    before returning cached rows.
    """

    def __init__(self, path: Path | None = None) -> None:
        """Initialize the repository.

        Args:
            path: Override the JSON file location for tests. Defaults to
                ``${CONFIG_DIR}/departments.json``.
        """
        self._path = path or (get_config_dir() / _FILENAME)
        self._cached_mtime_ns: int | None = None
        self._cached_rows: list[Department] | None = None

    @property
    def path(self) -> Path:
        """Return the absolute path to the registry file."""
        return self._path

    def list_all(self) -> list[Department]:
        """Return all registered departments (mtime-cached).

        Returns:
            Validated :class:`Department` rows. Empty list when the file
            does not yet exist.

        Raises:
            ValidationError: If the file is present but contains rows that
                fail Pydantic validation.
        """
        if not self._path.exists():
            self._cached_mtime_ns = None
            self._cached_rows = []
            return []
        current_mtime = self._path.stat().st_mtime_ns
        if (
            self._cached_rows is not None
            and self._cached_mtime_ns == current_mtime
        ):
            return list(self._cached_rows)
        rows = self._load_from_disk()
        self._cached_mtime_ns = current_mtime
        self._cached_rows = rows
        return list(rows)

    def find_by_alias(self, alias: str) -> Department | None:
        """Return the department with ``alias`` or None."""
        if not alias:
            raise ValueError("alias must be a non-empty string")
        for dept in self.list_all():
            if dept.alias == alias:
                return dept
        return None

    def add(self, payload: dict[str, Any]) -> Department:
        """Validate and persist a new department.

        Args:
            payload: Dict with the :class:`Department` field set.

        Returns:
            The validated :class:`Department` row.

        Raises:
            ValidationError: If the payload fails Pydantic validation.
            DuplicateAliasError: If a department with the same alias already
                exists.
        """
        candidate = Department.model_validate(payload)
        existing = self.list_all()
        if any(d.alias == candidate.alias for d in existing):
            raise DuplicateAliasError(
                f"department alias already registered: {candidate.alias}"
            )
        self._write_atomic([*existing, candidate])
        # Invalidate cache so the next read picks the new file mtime.
        self._cached_mtime_ns = None
        self._cached_rows = None
        return candidate

    def _load_from_disk(self) -> list[Department]:
        raw_text = self._path.read_text(encoding="utf-8")
        try:
            blob = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"departments.json is malformed JSON: {exc}") from exc
        if not isinstance(blob, dict) or "departments" not in blob:
            raise ValueError(
                "departments.json must be an object with a 'departments' list"
            )
        rows = []
        for entry in blob["departments"]:
            try:
                rows.append(Department.model_validate(entry))
            except ValidationError:
                # Constitution II: do not silently drop invalid rows; surface to
                # caller so the operator sees the malformed entry immediately.
                raise
        return rows

    def _write_atomic(self, rows: list[Department]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "departments": [
                json.loads(d.model_dump_json()) for d in rows
            ]
        }
        # tempfile.NamedTemporaryFile in the same directory so os.replace
        # is a POSIX same-filesystem atomic rename.
        fd, tmp_name = tempfile.mkstemp(
            prefix=".departments.", suffix=".json.tmp", dir=str(self._path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, str(self._path))
        except Exception:
            # Atomic-write contract: the tmp file must be cleaned up on any
            # failure path so the directory does not accumulate ``.tmp`` debris.
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                # intentional-skip: tmp may have been renamed before the failure
                pass
            raise
