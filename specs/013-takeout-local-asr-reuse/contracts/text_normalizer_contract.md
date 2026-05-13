# Contract: services/text_normalizer.py

**Module**: `src/tube_scout/services/text_normalizer.py` (신규)
**Spec FR mapping**: FR-024~FR-026.
**Boundary**: 본 spec 신규. 분석 입력의 단일 표준.

---

## 함수 시그니처

```python
from pathlib import Path
from tube_scout.models.content import TranscriptNormalized

NORMALIZER_VERSION: str = "v1.0"   # research §R-10

def normalize_transcript_text(text: str) -> str:
    """Normalize raw transcript text per FR-024.

    Order (idempotent):
      1) NFC unicode normalization
      2) ASR meta-marker strip ([음악], [박수], (...), <...>, *...*, ♪...♪)
      3) Punctuation removal (. , ? ! ~ … " ' ` ‘ ’ “ ” 、 。)
      4) Whitespace collapse (\\s+ → single space)
      5) Lowercase folding for Latin chars only

    Args:
        text: 원본 세그먼트 텍스트.

    Returns:
        정규화된 텍스트. 공백 strip 적용. 빈 입력은 빈 문자열.
    """

def normalize_transcript_json(
    raw_json_path: Path,
    normalized_json_path: Path,
    *,
    force: bool = False,
) -> bool:
    """Normalize a raw transcript JSON file to normalized output.

    Reads:
        01_collect/transcripts/<video_id>.json (E-6 schema)

    Writes:
        01_collect/transcripts_normalized/<video_id>.json (E-7 schema)

    Args:
        raw_json_path: 입력 자막 JSON.
        normalized_json_path: 출력 자막 JSON.
        force: True 시 기존 정규화 결과 덮어쓰기.

    Returns:
        True=write 발생, False=skip(기존 출력의 normalizer_version이 NORMALIZER_VERSION과 일치하고 force=False).

    Raises:
        FileNotFoundError: raw_json_path 부재.
        ValueError: raw JSON schema 위반 (segments 키 부재 등).
    """

def detect_source_conflict(transcripts_dir: Path, video_id: str) -> str | None:
    """Detect single-source rule violation (FR-024).

    Returns:
        None if no conflict; else an actionable message string describing
        which two source files coexist.

    Note:
        본 함수는 메시지 생성만 — 호출자(normalize CLI)가 exit 결정.
    """
```

---

## 정규화 결과 schema (E-7)

```json
{
  "video_id": "sUJbkkYzNGc",
  "language": "ko",
  "source_type": "asr",
  "normalizer_version": "v1.0",
  "normalized_at": "2026-05-13T11:05:00+09:00",
  "segments": [
    {"start": 0.0, "end": 3.5, "text": "안녕하세요 정광석 교수입니다"}
  ]
}
```

`source_type` 도출 규칙:
- raw `source == 'whisper'` → `'asr'`
- raw `source == 'captions_api'` → `'api'`
- raw `source == 'transcript_api'` → `'api'` (spec 010 호환)
- raw `source == 'manual'` (현재 미생성, 향후 확장) → `'manual'`

---

## Single-source rule 검증 (FR-024)

`detect_source_conflict` 의사코드:

```python
def detect_source_conflict(transcripts_dir, video_id):
    raw_path = transcripts_dir / f"{video_id}.json"
    if not raw_path.exists():
        return None
    raw = json.loads(raw_path.read_text())
    source = raw.get("source")
    # 현재는 단일 파일 패턴이라 conflict 가능성 0. 미래에 출처별 파일 분리 시 활용 — 본 spec에서는
    # 운영자가 같은 영상을 두 번 수집하지 않는 한 발생 0. 안전망으로 audit-log "single_source_ok" 출력.
    return None
```

**현재 구현**: 같은 video_id에 raw JSON은 항상 1개 — `01_collect/transcripts/<video_id>.json`. ASR과 API caption이 같은 영상을 처리하면 후속이 atomic write로 덮어쓰지만, `processing_status.caption_source` 이전 값을 보존하지 않음 — 운영자가 의도적으로 두 번 실행한 경우. 정책 위반은 운영자 사전 결정으로 차단.

**미래 확장 시**: 같은 video_id에 `transcripts/<id>__asr.json` / `<id>__api.json` 분리 저장 옵션 등 추가하려면 이 함수가 둘 다 검출하여 conflict 보고. 본 spec에서는 single-file 패턴 유지.

---

## 멱등성

- 같은 raw JSON + 같은 NORMALIZER_VERSION → 같은 출력. atomic tempfile + rename.
- 출력 파일의 `normalizer_version` 메타가 입력과 일치하면 skip (force=False).
- NORMALIZER_VERSION bump 시 자동 재정규화 트리거(force=True 권장).

---

## 테스트 진입점

- `tests/contract/test_text_normalizer_contract.py`:
  - `test_normalize_transcript_text_is_idempotent` (n(n(x)) == n(x))
  - `test_normalize_strips_meta_markers` ([음악], [박수], (배경음) etc.)
  - `test_normalize_strips_punctuation` (./,/?/!/…)
  - `test_normalize_nfc_handles_jamo_isolated` (가 → 가)
  - `test_normalize_lowercases_latin_only` (한글 영향 0)
  - `test_normalize_collapses_whitespace_and_newlines`
  - `test_normalize_transcript_json_writes_atomic` (tmp + rename)
  - `test_normalize_transcript_json_skips_when_version_matches`
  - `test_normalize_transcript_json_force_rewrites`

---

## CLI 통합

`cli/collect.py` 의 `--auto-normalize` 기본 on:

```python
if auto_normalize:
    for video in processed_videos:
        normalize_transcript_json(
            transcripts_dir / f"{video.video_id}.json",
            normalized_dir / f"{video.video_id}.json",
            force=False,
        )
```

`cli/<process module>.py` 의 `tube-scout process normalize-transcripts` 단독 명령은 같은 함수 호출, `--force` 옵션 그대로 전달.
