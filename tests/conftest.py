"""Shared test fixtures for tube-scout."""

import os
import resource
from collections.abc import Generator
from pathlib import Path

import pytest

# Hard cap pytest process memory at 10 GiB on 13 GB-RAM dev hosts.
# Without this, runaway collection/fixtures have hit 12 GB anon-rss and
# triggered the kernel OOM-killer on the ghostty cgroup, taking down the
# whole interactive session (shell + Claude Code + dev-squad agents).
# Crossing this cap surfaces as a normal `MemoryError` in the offending
# test instead. Disable by exporting `TUBE_SCOUT_NO_MEM_CAP=1`.
if not os.environ.get("TUBE_SCOUT_NO_MEM_CAP"):
    _MEMORY_CAP_BYTES = 10 * 1024**3
    for _rlimit in (resource.RLIMIT_AS, resource.RLIMIT_DATA):
        try:
            _soft, _hard = resource.getrlimit(_rlimit)
            resource.setrlimit(
                _rlimit,
                (_MEMORY_CAP_BYTES, max(_hard, _MEMORY_CAP_BYTES)),
            )
        except (ValueError, OSError):
            pass

# pytest-httpx provides httpx_mock fixture automatically via its plugin.
# tests.fixtures.httpx_mock re-exports HTTPXMock type + response builders for
# contract tests (spec 009 T008–T010).
from tests.fixtures.httpx_mock import HTTPXMock as HTTPXMock  # noqa: F401


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add ``--run-manual`` opt-in for tests/manual/* (FR-IDEA6-009)."""
    parser.addoption(
        "--run-manual",
        action="store_true",
        default=False,
        help="Collect tests/manual/* (require live OAuth credentials).",
    )


def pytest_collection_modifyitems(  # type: ignore[no-untyped-def]
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip tests under ``tests/manual/`` unless ``--run-manual`` is set."""
    if config.getoption("--run-manual"):
        return
    skip_manual = pytest.mark.skip(reason="needs --run-manual (FR-IDEA6-009)")
    for item in items:
        if "tests/manual" in str(item.fspath):
            item.add_marker(skip_manual)


@pytest.fixture(autouse=True)
def _isolated_tokens_dir(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Auto-isolate the OAuth tokens directory per test.

    Spec 009 introduced a hard registry check (resolve_channel_alias) on
    every collect command. Without isolation, tests inherit the dev's
    real ~/.config/tube-scout/tokens/channels.json — passing locally but
    failing in CI where that file is empty. This fixture points
    TUBE_SCOUT_TOKENS_DIR at a fresh tmp dir AND pre-registers a
    "nursing" alias so existing tests that rely on a single registered
    alias (auto-select branch) or on alias="nursing" continue to work.
    """
    import json
    from datetime import UTC, datetime

    tokens_dir = tmp_path_factory.mktemp("tube_scout_tokens")
    monkeypatch.setenv("TUBE_SCOUT_TOKENS_DIR", str(tokens_dir))

    now = datetime.now(UTC).isoformat()
    registry = {
        "nursing": {
            "alias": "nursing",
            "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
            "channel_name": "Test Channel",
            "registered_at": now,
            "last_used_at": now,
            "token_path": str(tokens_dir / "nursing.json"),
        }
    }
    (tokens_dir / "channels.json").write_text(json.dumps(registry), encoding="utf-8")
    (tokens_dir / "nursing.json").write_text("{}", encoding="utf-8")
    return tokens_dir


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory structure for tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "raw" / "channels").mkdir(parents=True)
    (data_dir / "raw" / "comments").mkdir(parents=True)
    (data_dir / "raw" / "retention").mkdir(parents=True)
    (data_dir / "raw" / "transcripts").mkdir(parents=True)
    (data_dir / "raw" / "analytics").mkdir(parents=True)
    (data_dir / "processed" / "sentiment").mkdir(parents=True)
    (data_dir / "processed" / "segments").mkdir(parents=True)
    (data_dir / "processed" / "eqs").mkdir(parents=True)
    (data_dir / "processed" / "forecast").mkdir(parents=True)
    (data_dir / "reports" / "video").mkdir(parents=True)
    (data_dir / "reports" / "channel").mkdir(parents=True)
    (data_dir / "checkpoints").mkdir(parents=True)
    return data_dir


@pytest.fixture
def tmp_projects_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path, None, None]:
    """Yield a temporary projects root directory and patch env + CWD defaults.

    Patches TUBE_SCOUT_PROJECTS_DIR so that any ProjectManager constructed
    without an explicit ``projects_root`` argument uses this temp directory
    instead of a relative ``./projects`` that would pollute the working tree.
    """
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("TUBE_SCOUT_PROJECTS_DIR", str(root))
    yield root


@pytest.fixture
def tmp_project(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Create a temporary project with ProjectManager."""
    from tube_scout.output.manager import ProjectManager

    mgr = ProjectManager(projects_root=tmp_path / "projects")
    mgr.create_project()
    return mgr


@pytest.fixture
def mock_api_responses_dir() -> Path:
    """Return path to mock API response fixtures directory."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    fixtures_dir.mkdir(exist_ok=True)
    return fixtures_dir


@pytest.fixture
def sample_channel_id() -> str:
    """Return a sample YouTube channel ID for testing."""
    return "UCxxxxxxxxxxxxxxxxxxxxxx"


@pytest.fixture
def sample_professor_name() -> str:
    """Return a sample professor name for testing."""
    return "TestProfessor"
