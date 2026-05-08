"""Adversary tests for spec 010 (`--prefer-captions-api` + skip-existing resume).

Covers Acceptance Criteria A5 of `specs/010-prefer-captions-resume/spec.md`
with 12 personas spanning:

(a) cache integrity: corrupt JSON, missing `segments`, empty `segments`,
    file-as-directory (EC-010-A/B/C/G)
(b) flag composition: `--prefer-captions-api` alone, with `--force-refresh`,
    without Captions API client (EC-010-D/E)
(c) audit CSV correctness: `skipped` rows + `hint` format (FR-010-06,
    Output Format section)
(d) silent-skip detector: orchestrator must surface both flags as CLI params
    AND must thread `prefer_captions_api` into the service call
    (Rule 4 enforcement)
(e) regression-of-default: with both flags off, `TranscriptService` behavior
    is byte-identical to spec-009 master (FR-010-07)
(f) priority + quota: `--prefer-captions-api` quota-exceeded HttpError must
    fall through to scraper (EC-010-I)

Tests that PASS today (defensive behavior already correct in spec-009
master) stay green. Tests that codify the *future* spec-010 contract are
marked `xfail(strict=True)` so each future-impl XPASS flips one strict
marker, signaling the marker can be removed in a follow-up commit.

Anonymized fixtures only: `private_vid_001..N`, `public_vid_001..N`,
`Holgil-dong`, `Kim Younghee`. No real video IDs, no real instructor names.
"""

from __future__ import annotations

import inspect
import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------


def _make_fake_yt_service(
    *,
    list_items: list[dict[str, Any]] | None = None,
    list_raises: BaseException | None = None,
    download_payload: str | bytes | None = None,
    download_raises: BaseException | None = None,
) -> MagicMock:
    """Build a MagicMock for the googleapiclient YouTube service captions().

    Mirrors the chain ``service.captions().list(...).execute()`` and
    ``service.captions().download(...).execute()`` used by
    :class:`tube_scout.services.captions_api.CaptionsAPIClient`.
    """
    captions_ns = MagicMock()

    list_call = MagicMock()
    if list_raises is not None:
        list_call.execute.side_effect = list_raises
    else:
        list_call.execute.return_value = {"items": list_items or []}
    captions_ns.list.return_value = list_call

    dl_call = MagicMock()
    if download_raises is not None:
        dl_call.execute.side_effect = download_raises
    else:
        dl_call.execute.return_value = download_payload or b""
    captions_ns.download.return_value = dl_call

    svc = MagicMock()
    svc.captions.return_value = captions_ns
    return svc


def _build_scraper_with_manual(text: str = "hello") -> MagicMock:
    """Mock youtube-transcript-api primary path that yields a manual track."""
    manual = MagicMock()
    manual.fetch.return_value = [
        {"text": text, "start": 0.0, "duration": 1.0},
    ]
    tlist = MagicMock()
    tlist.find_manually_created_transcript.return_value = manual
    scraper = MagicMock()
    scraper.list.return_value = tlist
    return scraper


def _write_cache(dir_: Path, vid: str, payload: dict[str, Any]) -> Path:
    """Drop a transcripts/<vid>.json fixture file."""
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / f"{vid}.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _valid_cache_payload(vid: str, n: int = 3) -> dict[str, Any]:
    return {
        "video_id": vid,
        "transcript_type": "manual",
        "source": "manual",
        "segments": [
            {"text": f"seg{i}", "start": float(i), "duration": 1.0}
            for i in range(n)
        ],
    }


# ===========================================================================
# Persona 1 — IpBlockedRecoveryPersona  (US1 / EC-010-D)
# Captions API succeeds; scraper would IP-block. With `prefer_captions_api`
# kwarg passed to fetch_transcript, the run completes and never touches
# the scraper.
# ===========================================================================


class TestIpBlockedRecoveryPersona:
    """FR-010-03 — Captions-API-first means scraper IP block is irrelevant."""

    def test_prefer_captions_skips_scraper_after_ip_block(self) -> None:
        from tube_scout.services.captions_api import CaptionsAPIClient
        from tube_scout.services.transcript import TranscriptService

        srt = (
            "1\n00:00:00,000 --> 00:00:02,000\nhello\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nworld\n\n"
        )
        client = CaptionsAPIClient(
            youtube_service=_make_fake_yt_service(
                list_items=[
                    {"id": "cap_1", "snippet": {"language": "ko", "trackKind": ""}}
                ],
                download_payload=srt,
            ),
        )
        service = TranscriptService(captions_api_client=client)

        # Make the scraper path explode; if prefer_captions_api wins, untouched.
        service._api = MagicMock()  # type: ignore[attr-defined]
        service._api.list.side_effect = RuntimeError(
            "youtube-transcript-api: IP blocked"
        )

        result = service.fetch_transcript(
            "public_vid_001",
            prefer_captions_api=True,  # type: ignore[call-arg]
        )
        assert result is not None
        assert result["source"] == "captions_api"

    def test_default_mode_signature_still_works(self) -> None:
        """Regression: today's signature must keep working (no TypeError)."""
        from tube_scout.services.transcript import TranscriptService

        service = TranscriptService()
        sig = inspect.signature(service.fetch_transcript)
        assert "video_id" in sig.parameters


# ===========================================================================
# Persona 2 — EmptyCaptionsApiPersona  (US1 acceptance #3 / EC-010-D, F)
# Captions API returns no track or 0-segment SRT. With prefer_captions_api,
# fall through to scraper.
# ===========================================================================


class TestEmptyCaptionsApiPersona:
    def test_empty_captions_api_falls_through_to_scraper(self) -> None:
        from tube_scout.services.captions_api import CaptionsAPIClient
        from tube_scout.services.transcript import TranscriptService

        client = CaptionsAPIClient(
            youtube_service=_make_fake_yt_service(list_items=[]),
        )
        service = TranscriptService(captions_api_client=client)
        service._api = _build_scraper_with_manual()  # type: ignore[attr-defined]

        result = service.fetch_transcript(
            "public_vid_001",
            prefer_captions_api=True,  # type: ignore[call-arg]
        )
        assert result is not None
        assert result["source"] == "manual"

    def test_prefer_without_client_runs_scraper_only(self) -> None:
        from tube_scout.services.transcript import TranscriptService

        service = TranscriptService(captions_api_client=None)
        service._api = _build_scraper_with_manual()  # type: ignore[attr-defined]

        result = service.fetch_transcript(
            "public_vid_001",
            prefer_captions_api=True,  # type: ignore[call-arg]
        )
        assert result is not None
        assert result["source"] == "manual"


# ===========================================================================
# Persona 3 — CorruptCacheFilePersona  (US2 acceptance #3 / EC-010-A,B)
# Existing transcripts/<vid>.json with invalid JSON or missing `segments`
# key must not crash; orchestrator must re-fetch.
# ===========================================================================


class TestCorruptCacheFilePersona:
    """Validate cache-validity helper used by FR-010-04."""

    def test_corrupt_json_raises_at_low_level_so_orchestrator_must_catch(
        self, tmp_path: Path
    ) -> None:
        """`read_json` bubbles JSONDecodeError; orchestrator MUST catch it.

        Pins the current low-level behavior. Acts as a contract for the
        orchestrator: it must wrap read_json in try/except rather than let
        a single corrupt cache abort the whole run.
        """
        from tube_scout.storage.json_store import read_json

        bad = tmp_path / "private_vid_001.json"
        bad.write_text("{not valid json", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            read_json(bad)

    def test_orchestrator_helper_rejects_corrupt_json(self, tmp_path: Path) -> None:
        from tube_scout.cli import collect as collect_mod

        helper = getattr(collect_mod, "_is_valid_cached_transcript", None)
        assert helper is not None, (
            "orchestrator must expose _is_valid_cached_transcript(path) -> bool"
        )

        cache_dir = tmp_path / "transcripts"
        cache_dir.mkdir()
        bad = cache_dir / "private_vid_001.json"
        bad.write_text("{not valid json", encoding="utf-8")
        assert helper(bad) is False

    def test_missing_segments_key_treated_as_missing(self, tmp_path: Path) -> None:
        from tube_scout.cli import collect as collect_mod

        helper = getattr(collect_mod, "_is_valid_cached_transcript")
        cache_dir = tmp_path / "transcripts"
        p = _write_cache(
            cache_dir,
            "private_vid_001",
            {"video_id": "private_vid_001", "transcript_type": "manual"},
        )
        assert helper(p) is False


# ===========================================================================
# Persona 4 — EmptySegmentsCachePersona  (US2 acceptance #4 / EC-010-C)
# `{"segments": []}` is treated as a previous failed-but-written record
# and re-fetched.
# ===========================================================================


class TestEmptySegmentsCachePersona:
    def test_empty_segments_treated_as_miss(self, tmp_path: Path) -> None:
        from tube_scout.cli import collect as collect_mod

        helper = getattr(collect_mod, "_is_valid_cached_transcript")
        p = _write_cache(
            tmp_path / "transcripts",
            "public_vid_002",
            {"video_id": "public_vid_002", "segments": []},
        )
        assert helper(p) is False

    def test_non_empty_segments_is_valid(self, tmp_path: Path) -> None:
        from tube_scout.cli import collect as collect_mod

        helper = getattr(collect_mod, "_is_valid_cached_transcript")
        p = _write_cache(
            tmp_path / "transcripts",
            "public_vid_003",
            _valid_cache_payload("public_vid_003", n=5),
        )
        assert helper(p) is True


# ===========================================================================
# Persona 5 — FileAsDirectoryPersona  (EC-010-G)
# `<vid_id>.json` exists but is a *directory*. Validity helper must say
# False; orchestrator must surface a per-video failure (not abort the run).
# ===========================================================================


class TestFileAsDirectoryPersona:
    def test_directory_in_cache_path_is_invalid(self, tmp_path: Path) -> None:
        from tube_scout.cli import collect as collect_mod

        helper = getattr(collect_mod, "_is_valid_cached_transcript")
        cache_dir = tmp_path / "transcripts"
        bogus = cache_dir / "private_vid_001.json"
        bogus.mkdir(parents=True)
        assert helper(bogus) is False


# ===========================================================================
# Persona 6 — ForceRefreshConsistencyPersona  (US2 acceptance #2 / EC-010-E)
# `--force-refresh` ignores cache; existing files atomically overwritten.
# ===========================================================================


class TestForceRefreshConsistencyPersona:
    def test_cli_force_refresh_param_present(self) -> None:
        from tube_scout.cli.collect import collect_transcripts_command

        sig = inspect.signature(collect_transcripts_command)
        assert "force_refresh" in sig.parameters, (
            "spec 010 FR-010-02 mandates --force-refresh on collect transcripts"
        )

    def test_existing_write_json_is_atomic(self, tmp_path: Path) -> None:
        """FR-010-08 — `write_json` must use temp + os.replace.

        Inspect the implementation to lock in the atomic-write contract.
        """
        from tube_scout.storage import json_store

        src = inspect.getsource(json_store.write_json)
        assert "mkstemp" in src
        assert ".replace(" in src


# ===========================================================================
# Persona 7 — SigintMidWritePersona  (FR-010-08, EC-010-J)
# Concurrent writes / interrupted writes must never leave a half-written
# file that skip-existing would later treat as valid.
# ===========================================================================


class TestSigintMidWritePersona:
    def test_concurrent_writes_leave_valid_json(self, tmp_path: Path) -> None:
        """20 racing threads writing the same file: file always parses cleanly."""
        from tube_scout.storage.json_store import write_json

        target = tmp_path / "transcripts" / "private_vid_001.json"
        target.parent.mkdir(parents=True, exist_ok=True)

        payloads = [
            {"video_id": "private_vid_001", "n": i, "segments": [{"x": i}]}
            for i in range(20)
        ]
        errors: list[BaseException] = []

        def worker(p: dict[str, Any]) -> None:
            try:
                write_json(target, p)
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(p,)) for p in payloads]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert errors == [], f"unexpected write errors: {errors}"
        assert target.exists()
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded["video_id"] == "private_vid_001"

    def test_failed_write_does_not_leak_tmp(self, tmp_path: Path) -> None:
        """If json.dump raises, mkstemp file is unlinked. Half-written
        tempfiles must not later be misclassified by skip-existing.
        """
        from tube_scout.storage.json_store import write_json

        target = tmp_path / "transcripts" / "broken.json"
        target.parent.mkdir(parents=True, exist_ok=True)

        class Unjsonable:
            pass

        with pytest.raises(TypeError):
            write_json(target, {"x": Unjsonable()})

        leftovers = list(target.parent.glob(".json_*.tmp"))
        assert leftovers == [], f"leaked tmp files: {leftovers}"
        assert not target.exists()


# ===========================================================================
# Persona 8 — AuditCsvSkippedPersona  (US3 / FR-010-06 / Output Format)
# `skipped` classification token + hint format.
# ===========================================================================


class TestAuditCsvSkippedPersona:
    def test_skipped_classification_is_allowed(self) -> None:
        from tube_scout.services.transcripts_audit import ALLOWED_CLASSIFICATIONS

        assert "skipped" in ALLOWED_CLASSIFICATIONS

    def test_skipped_audit_row_round_trips_through_writer(
        self, tmp_path: Path
    ) -> None:
        """FR-010-06 — write_audit_csv must accept a 'skipped' row unchanged."""
        from tube_scout.services.transcripts_audit import (
            ALLOWED_CLASSIFICATIONS,
            write_audit_csv,
        )

        assert "skipped" in ALLOWED_CLASSIFICATIONS

        path = tmp_path / "audit.csv"
        rows = [
            {
                "video_id": "private_vid_001",
                "title": "Sample Lecture Week 13",
                "published_at": "2026-04-06T07:24:13Z",
                "privacy_status": "unlisted",
                "classification": "skipped",
                "hint": (
                    "Existing transcript at projects/X/01_collect/transcripts/"
                    "private_vid_001.json (5 segments); pass --force-refresh "
                    "to override."
                ),
            }
        ]
        write_audit_csv(rows, path)
        text = path.read_text(encoding="utf-8")
        assert "private_vid_001" in text
        assert "skipped" in text
        assert "--force-refresh" in text

    def test_existing_classifications_unchanged(self) -> None:
        """Regression: spec-009 classifications still present (no removal)."""
        from tube_scout.services.transcripts_audit import ALLOWED_CLASSIFICATIONS

        for token in (
            "private_no_captions_api",
            "transcripts_disabled",
            "no_caption_track",
            "api_error",
            "unknown",
        ):
            assert token in ALLOWED_CLASSIFICATIONS, (
                f"spec-009 token {token!r} disappeared — regression"
            )


# ===========================================================================
# Persona 9 — PriorityInversionRegressionPersona  (FR-010-07)
# Default mode (both flags off) MUST behave identically to spec-009 master.
# ===========================================================================


class TestPriorityInversionRegressionPersona:
    def test_default_mode_no_captions_call_for_public_video(self) -> None:
        """Public video w/ manual transcript: Captions API never queried."""
        from tube_scout.services.captions_api import CaptionsAPIClient
        from tube_scout.services.transcript import TranscriptService

        yt_service = _make_fake_yt_service(list_items=[])
        client = CaptionsAPIClient(youtube_service=yt_service)

        service = TranscriptService(captions_api_client=client)
        service._api = _build_scraper_with_manual()  # type: ignore[attr-defined]

        result = service.fetch_transcript("public_vid_001")
        assert result is not None
        assert result["source"] == "manual"

        # Critical regression assertion: Captions API service untouched.
        yt_service.captions.assert_not_called()

    def test_default_mode_signature_unchanged_for_legacy_callers(self) -> None:
        """Legacy callers passing only `video_id` (and optional `audio_path`)
        must keep working. The new `prefer_captions_api` kwarg is OPTIONAL.
        """
        from tube_scout.services.transcript import TranscriptService

        sig = inspect.signature(TranscriptService.fetch_transcript)
        params = list(sig.parameters.values())
        assert params[1].name == "video_id"
        for p in params[2:]:
            assert p.default is not inspect.Parameter.empty, (
                f"new param {p.name!r} must have a default to preserve "
                "spec-009 calling convention"
            )


# ===========================================================================
# Persona 10 — QuotaExhaustedDuringPreferPersona  (EC-010-I)
# Captions API quota-exceeded mid-run with `prefer_captions_api=True`.
# Service must treat as empty and fall through to scraper for that video;
# subsequent videos still try the API.
# ===========================================================================


class TestQuotaExhaustedDuringPreferPersona:
    def test_quota_exhausted_triggers_scraper_fallback(self) -> None:
        from tube_scout.services.captions_api import CaptionsAPIClient
        from tube_scout.services.transcript import TranscriptService

        client = CaptionsAPIClient(
            youtube_service=_make_fake_yt_service(list_items=[]),
        )
        # Simulate quota exhaustion — fetch_segments will short-circuit None.
        client._quota_used = client._quota_limit  # type: ignore[attr-defined]

        service = TranscriptService(captions_api_client=client)
        service._api = _build_scraper_with_manual()  # type: ignore[attr-defined]

        result = service.fetch_transcript(
            "public_vid_001",
            prefer_captions_api=True,  # type: ignore[call-arg]
        )
        assert result is not None
        assert result["source"] == "manual"

    def test_subsequent_videos_keep_trying_captions_api(self) -> None:
        from tube_scout.services.captions_api import CaptionsAPIClient
        from tube_scout.services.transcript import TranscriptService

        srt = "1\n00:00:00,000 --> 00:00:01,000\nhi\n\n"
        client = CaptionsAPIClient(
            youtube_service=_make_fake_yt_service(
                list_items=[
                    {"id": "cap_1", "snippet": {"language": "ko", "trackKind": ""}}
                ],
                download_payload=srt,
            ),
        )
        service = TranscriptService(captions_api_client=client)
        service._api = _build_scraper_with_manual()  # type: ignore[attr-defined]

        # Sanity: with quota available, video N+1 succeeds via API.
        result = service.fetch_transcript(
            "public_vid_002",
            prefer_captions_api=True,  # type: ignore[call-arg]
        )
        assert result is not None
        assert result["source"] == "captions_api"


# ===========================================================================
# Persona 11 — SilentSkipDetectorPersona  (Rule 4 enforcement)
# Catches the orchestrator-wiring gap: CLI accepts the flag but forgets to
# thread it through to the service call. Also ensures both flags appear on
# the CLI signature in the first place.
# ===========================================================================


class TestSilentSkipDetectorPersona:
    def test_cli_prefer_captions_api_param_present(self) -> None:
        from tube_scout.cli.collect import collect_transcripts_command

        sig = inspect.signature(collect_transcripts_command)
        assert "prefer_captions_api" in sig.parameters

    def test_cli_threads_flag_through_to_fetch_transcript(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tube_scout.cli.collect import collect_transcripts_command

        sig = inspect.signature(collect_transcripts_command)
        if "prefer_captions_api" not in sig.parameters:
            pytest.fail(
                "Pre-condition unmet: --prefer-captions-api param missing on CLI"
            )

        captured: dict[str, Any] = {}

        def fake_fetch(self: Any, video_id: str, **kwargs: Any) -> dict[str, Any]:
            captured["kwargs"] = dict(kwargs)
            captured["video_id"] = video_id
            return _valid_cache_payload(video_id, n=2)

        monkeypatch.setattr(
            "tube_scout.services.transcript.TranscriptService.fetch_transcript",
            fake_fetch,
        )

        with (
            patch("tube_scout.cli.collect.resolve_project") as mock_resolve,
            patch("tube_scout.cli.collect._load_config") as mock_cfg,
            patch(
                "tube_scout.services.auth.resolve_channel_alias",
                return_value="nursing",
            ),
            patch("tube_scout.services.auth.load_registry") as mock_reg,
            patch("tube_scout.services.auth.authenticate_channel"),
            patch("googleapiclient.discovery.build"),
        ):
            mock_mgr = MagicMock()
            collect_dir = tmp_path / "01_collect"
            collect_dir.mkdir()
            mock_mgr.collect_dir = collect_dir
            mock_resolve.return_value = mock_mgr

            from tube_scout.models.config import TRANSCRIPT_PROFILE

            mock_cfg.return_value = MagicMock(
                channels=[MagicMock(channel_id="UC_test_channel")],
                settings=MagicMock(rate_limit_transcript=TRANSCRIPT_PROFILE),
            )
            mock_reg.return_value = {
                "nursing": MagicMock(channel_id="UC_test_channel"),
            }

            ch_dir = collect_dir / "channels" / "UC_test_channel"
            ch_dir.mkdir(parents=True)
            (ch_dir / "videos_meta.json").write_text(
                json.dumps(
                    [
                        {
                            "video_id": "private_vid_001",
                            "title": "Holgil-dong Lecture Wk 13",
                            "published_at": "2026-04-06T07:24:13Z",
                            "privacy_status": "unlisted",
                        }
                    ]
                )
            )

            collect_transcripts_command(
                data_dir=str(tmp_path / "data"),
                project_dir=str(tmp_path / "projects"),
                project=None,
                video_id="private_vid_001",
                channel="nursing",
                prefer_captions_api=True,  # type: ignore[call-arg]
            )

        assert captured.get("kwargs", {}).get("prefer_captions_api") is True, (
            "Rule 4 violation: CLI flag did not reach fetch_transcript()"
        )


# ===========================================================================
# Persona 12 — SingleVideoCachePersona  (US2 acceptance #6 / EC-010-H)
# `--video-id <single>` with a cached file (no --force-refresh) must respect
# the cache and emit a `skipped` audit row, just like bulk mode.
# ===========================================================================


class TestSingleVideoCachePersona:
    def test_single_video_cached_skips_fetch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tube_scout.cli.collect import collect_transcripts_command

        sig = inspect.signature(collect_transcripts_command)
        if "force_refresh" not in sig.parameters:
            pytest.fail("Pre-condition unmet: --force-refresh param missing")

        called = {"fetch_calls": 0}

        def fake_fetch(self: Any, video_id: str, **kwargs: Any) -> dict[str, Any]:
            called["fetch_calls"] += 1
            return _valid_cache_payload(video_id)

        monkeypatch.setattr(
            "tube_scout.services.transcript.TranscriptService.fetch_transcript",
            fake_fetch,
        )

        with (
            patch("tube_scout.cli.collect.resolve_project") as mock_resolve,
            patch("tube_scout.cli.collect._load_config") as mock_cfg,
            patch(
                "tube_scout.services.auth.resolve_channel_alias",
                return_value="nursing",
            ),
            patch("tube_scout.services.auth.load_registry") as mock_reg,
            patch("tube_scout.services.auth.authenticate_channel"),
            patch("googleapiclient.discovery.build"),
        ):
            mock_mgr = MagicMock()
            collect_dir = tmp_path / "01_collect"
            collect_dir.mkdir()
            mock_mgr.collect_dir = collect_dir
            mock_resolve.return_value = mock_mgr

            from tube_scout.models.config import TRANSCRIPT_PROFILE

            mock_cfg.return_value = MagicMock(
                channels=[MagicMock(channel_id="UC_test_channel")],
                settings=MagicMock(rate_limit_transcript=TRANSCRIPT_PROFILE),
            )
            mock_reg.return_value = {
                "nursing": MagicMock(channel_id="UC_test_channel"),
            }

            cache_dir = collect_dir / "transcripts"
            cache_dir.mkdir(parents=True)
            _write_cache(
                cache_dir,
                "private_vid_001",
                _valid_cache_payload("private_vid_001", n=5),
            )

            ch_dir = collect_dir / "channels" / "UC_test_channel"
            ch_dir.mkdir(parents=True)
            (ch_dir / "videos_meta.json").write_text(
                json.dumps(
                    [
                        {
                            "video_id": "private_vid_001",
                            "title": "Kim Younghee Lecture Wk 1",
                            "published_at": "2026-04-06T07:24:13Z",
                            "privacy_status": "unlisted",
                        }
                    ]
                )
            )

            collect_transcripts_command(
                data_dir=str(tmp_path / "data"),
                project_dir=str(tmp_path / "projects"),
                project=None,
                video_id="private_vid_001",
                channel="nursing",
                force_refresh=False,  # type: ignore[call-arg]
            )

        assert called["fetch_calls"] == 0, (
            "single-video mode must skip cached file, not re-fetch it"
        )
