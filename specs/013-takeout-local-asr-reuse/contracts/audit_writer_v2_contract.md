# Contract: services/audit_writer.py (v2 — 8-stage generalization)

**Module**: `src/tube_scout/services/audit_writer.py` (기존 spec 012, 본 spec에서 확장)
**Spec FR mapping**: FR-057~FR-060.
**Boundary**: B-5 (spec 012 audit_writer 인프라 권위).

---

## 변경 정책 (Backward-Compat)

- spec 012의 기존 메서드 `append_transcript_row`, `append_fingerprint_row` 는 Phase 1~3 동안 그대로 유지(spec 012 회귀 테스트 보호).
- 본 spec은 일반화 메서드 `append_row(stage, row_dict)` 신규 추가 + stage별 frozen fieldnames 상수 정의.
- Phase 4 yt-dlp 삭제 시 spec 012 전용 메서드 deprecated 표시(remove는 2 release 후 별도 idea).

---

## 모듈 상수 (frozen fieldnames per stage)

```python
TAKEOUT_INGEST_FIELDNAMES: tuple[str, ...] = (
    "video_id", "result", "reason", "mp4_filename", "match_confidence", "score", "timestamp"
)
AUDIO_EXTRACT_FIELDNAMES: tuple[str, ...] = (
    "video_id", "result", "reason", "input_kind", "output_path", "wav_size_bytes", "elapsed_s", "timestamp"
)
TRANSCRIPTS_FIELDNAMES: tuple[str, ...] = (
    "video_id", "result", "reason", "source", "caption_source_detail", "timestamp", "cookies_source"
)
FINGERPRINT_FIELDNAMES: tuple[str, ...] = (
    "video_id", "result", "reason", "duration_sec", "fingerprint_input_policy", "timestamp", "cookies_source"
)
NORMALIZE_FIELDNAMES: tuple[str, ...] = (
    "video_id", "result", "reason", "input_source", "normalizer_version", "timestamp"
)
ANALYZE_FIELDNAMES: tuple[str, ...] = (
    "pair_id", "source_video_id", "target_video_id", "result", "reason", "matching_mode", "elapsed_s", "timestamp"
)
REPORT_FIELDNAMES: tuple[str, ...] = (
    "professor", "channel", "result", "reason", "format", "output_path", "pair_count", "appendix_count", "timestamp"
)
KB_EXPORT_FIELDNAMES: tuple[str, ...] = (
    "video_id", "result", "reason", "format", "output_path", "byte_count", "timestamp"
)

STAGE_FIELDNAMES: dict[str, tuple[str, ...]] = {
    "takeout_ingest": TAKEOUT_INGEST_FIELDNAMES,
    "audio_extract":  AUDIO_EXTRACT_FIELDNAMES,
    "transcripts":    TRANSCRIPTS_FIELDNAMES,
    "fingerprint":    FINGERPRINT_FIELDNAMES,
    "normalize":      NORMALIZE_FIELDNAMES,
    "analyze":        ANALYZE_FIELDNAMES,
    "report":         REPORT_FIELDNAMES,
    "kb_export":      KB_EXPORT_FIELDNAMES,
}

VALID_RESULTS: frozenset[str] = frozenset({"success", "skip", "fail"})
```

**spec.md FR-058 호환 명시**: 모든 stage fieldnames는 `video_id` (또는 stage가 pair-level일 때 `pair_id`/`source_video_id`/`target_video_id`), `result`, `reason`, `timestamp` 4 컬럼을 공통으로 포함한다. spec FR-058이 명시한 컬럼 규약(`event` 컬럼 미도입, `reason` 이 machine + human 식별자 모두 담당)을 그대로 반영. `reason` 값 vocabulary(대표): `ignored_by_policy`, `empty_transcript`, `language_mismatch`, `mapping_ambiguous`, `mapping_resolved_manual`, `asr_failed`, `retry_claimed`, `interrupted_audio_cleanup`, `force_skip_existing`, `normalizer_unchanged`.

---

## 클래스 확장

```python
class AuditWriter:
    """Append-only audit CSV writer (spec 012 + spec 013 generalization)."""

    def __init__(self, project_dir: Path) -> None:
        """Initialize. Creates 01_collect/ if missing."""

    def append_row(self, stage: str, row: dict) -> None:
        """Append a row to <project_dir>/01_collect/<stage>_audit.csv.

        Args:
            stage: One of STAGE_FIELDNAMES keys.
            row: Dict with at least all keys in STAGE_FIELDNAMES[stage].
                Extra keys are dropped (csv.DictWriter extrasaction='ignore').

        Raises:
            KeyError: stage not in STAGE_FIELDNAMES.
            ValueError: row['result'] not in VALID_RESULTS.
        """

    # spec 012 backward-compat shims (Phase 4 deprecation 후 별도 idea로 removal)
    def append_transcript_row(self, row: dict) -> None:
        """Deprecated — use append_row('transcripts', row) instead."""
        self.append_row("transcripts", row)

    def append_fingerprint_row(self, row: dict) -> None:
        """Deprecated — use append_row('fingerprint', row) instead."""
        self.append_row("fingerprint", row)
```

내부 `_append_row(csv_path, fieldnames, row)` 는 spec 012 그대로 — atomic tempfile + rename.

---

## Phase 4 잔존 정책 (FR-060)

본 모듈은 cross-stage utility로 자리매김 — `services/audit_writer.py` 위치 그대로 유지. Phase 4 yt-dlp 코드 삭제 시:

- 삭제 대상: `services/ytdlp_adapter.py`, `services/ytdlp_errors.py`, `services/srv3_parser.py`, `services/transcripts_audit.py` (있다면 — spec 012의 transcripts_audit.py가 별도 모듈이라면 audit_writer.py와 통합).
- 유지: `services/audit_writer.py` (본 모듈) — Phase 1~3에서 이미 8 stage 일반화 완료.
- 검증: Phase 4 회귀 테스트 (`tests/integration/test_phase4_legacy_removal.py`)가 audit_writer import 성공 + 8 stage append_row 호출 통과.

---

## 테스트 진입점

- `tests/contract/test_audit_writer_v2_contract.py`:
  - `test_stage_fieldnames_has_8_entries`
  - `test_append_row_rejects_unknown_stage` (KeyError)
  - `test_append_row_rejects_invalid_result` (ValueError, result ∉ VALID_RESULTS)
  - `test_append_row_drops_extra_keys` (extrasaction='ignore')
  - `test_append_row_writes_header_on_first_call_only`
  - `test_append_row_atomic_tempfile_rename_pattern`
- `tests/integration/test_audit_log_pipeline.py`:
  - 4단계(takeout_ingest → audio_extract → transcripts → analyze) 통합 시뮬레이션 → 4개 별도 CSV 파일 생성 + 각 frozen fieldnames 일치 검증.
- `tests/integration/test_phase4_legacy_removal.py`:
  - yt-dlp surface 제거 후 audit_writer import 정상 + 8 stage append_row 호출 성공.
- spec 012 회귀 테스트 (`tests/unit/test_audit_writer.py` 또는 spec 012 기존 위치) 그대로 통과.
