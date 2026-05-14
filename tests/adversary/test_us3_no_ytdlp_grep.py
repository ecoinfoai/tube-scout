"""Adversarial RED test for FR-046 — no yt-dlp surface left in the tree.

Target (spec 013 T088 / US3 / FR-046):
    After Phase 5 cleanup (T089–T094) the production tree MUST NOT contain
    any reference to the yt-dlp adapter:

        - the literal substring `ytdlp`           (covers `ytdlp_adapter`,
                                                   `_dispatch_ytdlp_transcripts`,
                                                   `ytdlp:auto`, `ytdlp:manual`,
                                                   alias keys, etc.)
        - the literal substring `yt-dlp`          (PyPI dist name, prose
                                                   references in CLAUDE.md)
        - the literal substring `--source ytdlp`  (CLI flag value, redundant
                                                   with `ytdlp` above but kept
                                                   explicit for blast-radius)
        - the literal substring `_dispatch_ytdlp_transcripts`
                                                  (the dispatch function name —
                                                   even comment references must
                                                   be gone)
        - the literal substring `srv3_parser`     (deleted service module)

    Search scope:
        - src/                  (production code, B-8 deletion in T089)
        - tests/                (test files — except this one and
                                 test_pipeline_edge / fixtures that
                                 legitimately keep tokens as historical
                                 records — see exclusions below)
        - CLAUDE.md             (Active Technologies + recent-changes log)

    Search exclusions (FR-046 + tasks.md T088 description):
        - this test file itself (it must mention the tokens to assert on them)
        - specs/012-ytdlp-adapter/    (deleted wholesale in T094, but spec
                                       dir is *outside* our search scope
                                       anyway — listed for clarity)
        - _archive/                   (frozen historical pivot notes,
                                       deliberately not cleaned up; FR-046
                                       only governs live surface)
        - .git/, __pycache__/, *.pyc  (VCS / bytecode)

Phase ordering:
    - This test is added BEFORE T089-T094 cleanup runs ⇒ it MUST RED on commit.
    - After T089-T094 + T093 (CLAUDE.md) finish, this test MUST GREEN.
    - T095 (full regression) re-runs this as part of the suite.

This is a pure file-tree grep — no imports of `tube_scout`, no fixtures,
no subprocess. Failure messages name every offending (file, line) so the
developer agent can fix them in one pass.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Forbidden literal substrings (FR-046). Each token is its own assertion
# bucket so the failure report tells the dev exactly which surface leaked.
FORBIDDEN_TOKENS: tuple[str, ...] = (
    "ytdlp",
    "yt-dlp",
    "--source ytdlp",
    "_dispatch_ytdlp_transcripts",
    "srv3_parser",
)

# Directory roots to scan, relative to REPO_ROOT. Anything outside these
# trees is out of scope for FR-046 (e.g. specs/, _archive/, .git/).
SEARCH_ROOTS: tuple[str, ...] = (
    "src",
    "tests",
)

# Single-file roots scanned in addition to SEARCH_ROOTS.
SEARCH_FILES: tuple[str, ...] = (
    "CLAUDE.md",
)

# Path *prefixes* (relative to REPO_ROOT, POSIX) that are excluded from
# the scan even if they fall under a SEARCH_ROOTS subtree. Exact-match
# files are listed in EXCLUDED_FILES.
EXCLUDED_PREFIXES: tuple[str, ...] = (
    "_archive/",
    "specs/012-ytdlp-adapter/",
    ".git/",
)

# Specific files excluded from the scan. This test file itself is the
# canonical example — it must reference the forbidden tokens in order to
# assert on them. Anything else added here needs a comment explaining
# why FR-046 does NOT apply.
EXCLUDED_FILES: frozenset[str] = frozenset(
    {
        # SELF: this file's literals are the assertion vocabulary.
        "tests/adversary/test_us3_no_ytdlp_grep.py",
        # T087 RED regression test references the forbidden module paths as
        # the very assertion vocabulary (parametrized importlib targets).
        "tests/integration/test_phase4_legacy_removal.py",
    }
)

# File extensions / names that are scanned. We deliberately skip binary
# artefacts (parquet, sqlite, png, mp4, …) and lockfiles whose presence
# is incidental.
SCANNED_SUFFIXES: tuple[str, ...] = (
    ".py",
    ".md",
    ".toml",
    ".nix",
    ".yaml",
    ".yml",
    ".json",
    ".html",
    ".jinja",
    ".jinja2",
    ".cfg",
    ".ini",
    ".txt",
)


def _is_excluded(rel_posix: str) -> bool:
    """Return True if this relative POSIX path is exempted from the scan."""
    if rel_posix in EXCLUDED_FILES:
        return True
    for prefix in EXCLUDED_PREFIXES:
        if rel_posix.startswith(prefix):
            return True
    # Belt-and-suspenders: skip __pycache__ no matter where it appears.
    if "/__pycache__/" in rel_posix or rel_posix.startswith("__pycache__/"):
        return True
    return False


def _iter_scanned_files() -> list[Path]:
    """Walk SEARCH_ROOTS + SEARCH_FILES and return scannable text files."""
    out: list[Path] = []
    for root in SEARCH_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if _is_excluded(rel):
                continue
            if path.suffix.lower() not in SCANNED_SUFFIXES:
                continue
            out.append(path)
    for fname in SEARCH_FILES:
        p = REPO_ROOT / fname
        if p.is_file() and not _is_excluded(fname):
            out.append(p)
    return out


def _find_offenders(token: str) -> list[tuple[str, int, str]]:
    """Return [(rel_path, line_no, line_text), ...] hits for `token`.

    Uses substring match (not regex) since all forbidden literals contain
    only ASCII / hyphens / underscores and we want zero ambiguity.
    """
    hits: list[tuple[str, int, str]] = []
    for path in _iter_scanned_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if token not in text:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        for idx, line in enumerate(text.splitlines(), start=1):
            if token in line:
                hits.append((rel, idx, line.rstrip()))
    return hits


# ---------------------------------------------------------------------------
# Persona 1 — "The Demolition Inspector"
# Walks every file post-Phase-5 and demands zero traces of the deleted
# adapter. Hardest possible assertion: substring match across the whole
# tree, no special-cases beyond the documented exclusions.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("token", FORBIDDEN_TOKENS)
def test_no_forbidden_token_anywhere_in_live_tree(token: str) -> None:
    """FR-046: token MUST NOT appear anywhere under src/, tests/, CLAUDE.md.

    Excludes this test file, `_archive/`, and `specs/012-ytdlp-adapter/`.
    """
    offenders = _find_offenders(token)
    if offenders:
        rendered = "\n".join(
            f"    {p}:{ln}: {body}" for (p, ln, body) in offenders[:60]
        )
        suffix = "" if len(offenders) <= 60 else f"\n    ... ({len(offenders) - 60} more)"
        pytest.fail(
            f"FR-046 violation: forbidden token {token!r} still present "
            f"in {len(offenders)} location(s):\n{rendered}{suffix}\n"
            "Remove all yt-dlp surface area (T089-T094) before this test can pass."
        )


# ---------------------------------------------------------------------------
# Persona 2 — "The Comment Archaeologist"
# Refuses to accept code deletion while comments still say `# yt-dlp does …`.
# Verified by SCANNED_SUFFIXES including `.py` and substring grep ignoring
# whether the match lives in a string, comment, or identifier.
# ---------------------------------------------------------------------------


def test_no_forbidden_token_in_python_comments_or_strings() -> None:
    """Catch the case where T089 deletes modules but T090/T093 leaves stale
    comments behind. Asserts that *no Python file* under src/ contains any
    of the tokens — broader than the parametrized scan because it focuses
    blame on production code."""
    leaks: list[tuple[str, int, str, str]] = []
    src_root = REPO_ROOT / "src"
    if not src_root.exists():
        pytest.skip("src/ not present — nothing to scan")
    for path in src_root.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if _is_excluded(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for token in FORBIDDEN_TOKENS:
            if token not in text:
                continue
            for idx, line in enumerate(text.splitlines(), start=1):
                if token in line:
                    leaks.append((rel, idx, token, line.rstrip()))
    if leaks:
        rendered = "\n".join(
            f"    {p}:{ln} ({tok!r}): {body}" for (p, ln, tok, body) in leaks[:60]
        )
        suffix = "" if len(leaks) <= 60 else f"\n    ... ({len(leaks) - 60} more)"
        pytest.fail(
            f"FR-046 violation in src/*.py: {len(leaks)} yt-dlp reference(s) "
            f"remain in production code:\n{rendered}{suffix}"
        )


# ---------------------------------------------------------------------------
# Persona 3 — "The Dependency Auditor"
# Specifically inspects pyproject.toml + flake.nix for the PyPI distribution
# name `yt-dlp` (with hyphen). FR-046 names these two files explicitly.
# ---------------------------------------------------------------------------


def test_pyproject_has_no_yt_dlp_dependency() -> None:
    """FR-046: pyproject.toml `dependencies` and any optional-dependency
    block MUST NOT list `yt-dlp`."""
    pyproject = REPO_ROOT / "pyproject.toml"
    if not pyproject.is_file():
        pytest.fail("pyproject.toml missing — cannot verify FR-046 cleanup")
    text = pyproject.read_text(encoding="utf-8")
    # PyPI distribution name uses a hyphen. Catch quoted forms ("yt-dlp",
    # 'yt-dlp', yt-dlp>=…) without false-positiving on prose.
    pattern = re.compile(r"['\"]yt-dlp(?:\[[^\]]*\])?(?:[<>=!~]=?[^'\"]*)?['\"]")
    hits = [
        (idx, line.rstrip())
        for idx, line in enumerate(text.splitlines(), start=1)
        if pattern.search(line)
    ]
    if hits:
        rendered = "\n".join(f"    pyproject.toml:{ln}: {body}" for (ln, body) in hits)
        pytest.fail(
            f"FR-046 violation: pyproject.toml still declares yt-dlp:\n{rendered}"
        )


def test_flake_nix_has_no_yt_dlp_package() -> None:
    """FR-046: flake.nix devShell MUST NOT include any `yt-dlp` package
    reference."""
    flake = REPO_ROOT / "flake.nix"
    if not flake.is_file():
        pytest.skip("flake.nix not present in this checkout")
    text = flake.read_text(encoding="utf-8")
    # Nix attribute path uses an underscore (`pkgs.yt-dlp` is the actual
    # attribute name — Nix allows hyphens in attr names). Match both
    # styles defensively.
    hits = [
        (idx, line.rstrip())
        for idx, line in enumerate(text.splitlines(), start=1)
        if ("yt-dlp" in line) or ("yt_dlp" in line)
    ]
    if hits:
        rendered = "\n".join(f"    flake.nix:{ln}: {body}" for (ln, body) in hits)
        pytest.fail(
            f"FR-046 violation: flake.nix still references yt-dlp:\n{rendered}"
        )


# ---------------------------------------------------------------------------
# Persona 4 — "The CLI Surface Skeptic"
# Demands that `--source ytdlp` is no longer documented anywhere a user
# could plausibly find it (help text, docstrings, tutorials, CLAUDE.md).
# Subsumed by Persona 1 but kept as a dedicated regression so a single-file
# regression on CLI docs is reported clearly.
# ---------------------------------------------------------------------------


def test_no_source_ytdlp_flag_documented_anywhere() -> None:
    """FR-046: the literal `--source ytdlp` MUST NOT survive Phase 5."""
    hits = _find_offenders("--source ytdlp")
    if hits:
        rendered = "\n".join(f"    {p}:{ln}: {body}" for (p, ln, body) in hits)
        pytest.fail(
            "FR-046 violation: `--source ytdlp` flag still documented:\n"
            f"{rendered}\n"
            "T090 must strip the dispatch branch AND CLI help text."
        )


# ---------------------------------------------------------------------------
# Persona 5 — "The Module Vivisectionist"
# Verifies that the four named service files were physically removed,
# not merely emptied or re-exported.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel",
    [
        "src/tube_scout/services/ytdlp_adapter.py",
        "src/tube_scout/services/ytdlp_errors.py",
        "src/tube_scout/services/srv3_parser.py",
    ],
)
def test_ytdlp_service_module_deleted(rel: str) -> None:
    """FR-046: these three service files MUST be deleted, not stubbed.

    `audio_fingerprint.py` is intentionally NOT in this list: it depends
    on `pyacoustid` and is retained per the FR-046 note ("`pyacoustid`
    MUST be retained — `services/audio_fingerprint.py` (B-7) still
    depends on it.")
    """
    path = REPO_ROOT / rel
    assert (
        not path.exists()
    ), f"FR-046: expected {rel} to be deleted in T089, but it still exists."
