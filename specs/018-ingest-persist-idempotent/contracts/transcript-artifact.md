# Contract: Transcript Artifact JSON Schema

**Spec**: [../spec.md](../spec.md) | **Plan**: [../plan.md](../plan.md) | **FR**: 018A, 018H
**Surface**: 분리 명령 `collect transcripts` (cli/collect.py:2249-2300) ⇋ 통합 명령 `collect ingest` (services/unified_ingest.py 의 `_persist_transcript`)

## 1. 영구화 위치

```text
data/<alias>/02_analyze/transcripts/<video_id>.json
```

- `<alias>` — spec 003 / 016 에 등록된 학과 alias (예: `nursing`, `dental_hygiene`)
- `<video_id>` — 11-char YouTube video ID
- 단일 파일이 atomic write 단위

## 2. JSON Schema (top-level keys 7 개)

```json
{
  "video_id": "string (11 chars, YouTube ID)",
  "source": "string (예: 'asr:faster-whisper:large-v3:int8_float16')",
  "language": "string (ISO 639-1, 예: 'ko')",
  "duration": 0.0,
  "segments": [/* segment 객체 list */],
  "asr_quality_flags": {/* 6 keys, see §3 */},
  "fetched_at": "string (ISO 8601 UTC)"
}
```

### 2.1 Segment 객체 (segments list 의 각 원소)

| Key | Type | Range / Description |
|---|---|---|
| `start` | float | 초 단위 시작 시각, ≥ 0 |
| `end` | float | 초 단위 종료 시각, > start |
| `text` | str | 인식된 텍스트 (앞뒤 공백 strip) |
| `compression_ratio` | float | faster-whisper 산출, ≥ 0 |
| `no_speech_prob` | float | faster-whisper 산출, 0.0–1.0 |

## 3. `asr_quality_flags` 의 내부 schema (spec 013 FR-018 보존)

| Key | Type | Description |
|---|---|---|
| `hallucination_repeat` | bool | 3+ 연속 동일 segment (환각 반복) |
| `vad_over_truncated` | bool | VAD 과잉 자름 (현재 항상 False, TODO) |
| `language_mismatch` | bool | 감지 언어 ≠ 기대 언어 (예: ko 기대인데 en 감지) |
| `short_segments_excess` | bool | 0.5s 미만 segment 가 30% 초과 |
| `silence_hallucination` | bool | 침묵 구간에 학습 잔재 패턴 감지 |
| `compression_ratio_violations` | int | 압축률 2.4 초과 segment 수 (count, not bool) |

## 4. 분리 / 통합 명령 동치성 (FR-018H, SC-018-5)

분리 명령 `collect transcripts` 가 생성하는 transcript json 의 키 집합과 통합 명령 `collect ingest` 가 생성하는 transcript json 의 키 집합은 **schema-for-schema 동치** 다 — top-level 7 키 + `asr_quality_flags` 의 6 종 flag 키 + segment 객체의 키가 모두 일치한다. segment 의 값 (timestamp, text 등) 과 `fetched_at` 은 호출마다 자연스럽게 달라지므로 동치 대상에서 제외. spec 011 의 입력 reader 는 두 경로의 산출물을 분기 없이 소비할 수 있다.

### 4.1 동치성 검증 contract test

```python
def test_transcript_artifact_schema_equivalence(
    tmp_path: Path, fixture_archive: Path
) -> None:
    """spec 013 분리 명령 + spec 018 통합 명령 산출물의 키 집합 일치."""
    # 분리 명령으로 alias_a 적재
    run_cli(["collect", "takeout", "--takeout-dir", fixture_archive, "--alias", "a"])
    run_cli(["collect", "transcripts", "--alias", "a"])
    json_a = json.loads(
        (tmp_path / "data/a/02_analyze/transcripts/VID00001.json").read_text()
    )

    # 통합 명령으로 alias_b 적재
    run_cli(["collect", "ingest", "--takeout-dir", fixture_archive, "--alias", "b"])
    json_b = json.loads(
        (tmp_path / "data/b/02_analyze/transcripts/VID00001.json").read_text()
    )

    # 키 집합 동치
    assert sorted(json_a.keys()) == sorted(json_b.keys())
    assert sorted(json_a["asr_quality_flags"].keys()) == sorted(json_b["asr_quality_flags"].keys())
    # segment 객체 키 동치 (값은 비결정성 → 키만)
    if json_a["segments"] and json_b["segments"]:
        assert sorted(json_a["segments"][0].keys()) == sorted(json_b["segments"][0].keys())
```

## 5. Atomic write 규약 (FR-018A)

### 5.1 Write 알고리즘

```python
fd, tmp_name = tempfile.mkstemp(dir=transcript_dir, suffix=".tmp")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(transcript_dict, f, ensure_ascii=False, indent=2)
    os.replace(tmp_name, dst_json_path)
except Exception:
    try:
        os.unlink(tmp_name)
    except OSError:
        pass
    raise
```

### 5.2 Atomicity 보장

- POSIX `rename(2)` 의 원자성에 의존 — 동일 파일시스템 내 rename 은 부분 상태가 관측되지 않음.
- 호출 종료 시점에 `transcript_dir` 안에 `*.tmp` 파일 0 개 (SC-018-2).
- 예외 발생 시 임시 파일이 cleanup 되며 부분 작성된 dst json 도 남지 않음.

### 5.3 위험 상황 (Edge cases)

- `*.tmp` 잔재 (이전 호출의 atomic write 실패) → 본 PATCH 의 가드 평가는 `*.tmp` 를 무시 (`Path(f"{video_id}.json").exists()` 만 평가). 다음 atomic write 가 자연스럽게 덮어쓴다.
- `transcript_dir` 의 권한 부족 (atomic write 실패) → PermissionError 가 raise 되며 retry_pending.json 에 등재.

## 6. 멱등 가드 결합 (FR-018C)

```python
def has_transcript(transcript_dir: Path, video_id: str) -> bool:
    """자막 단계 멱등 가드 — json 파일 존재 여부."""
    return (transcript_dir / f"{video_id}.json").exists()
```

`force=False` 시 `has_transcript()` True 인 영상은 자막 단계 skip, audit reason `already_transcribed`.

## 7. 후속 reader 의 의무 (spec 011 입력 계약)

- json read 시 `asr_quality_flags` 의 6 키 모두 존재함을 가정 (`AsrQualityFlags` pydantic 검증 통과).
- `segments` 가 empty list 인 경우는 ASR 결과 segment 0 개 (silent video, length 0 등) — reader 는 fallback 처리.
- `language` 가 expected language 와 다른 경우 (`asr_quality_flags.language_mismatch=True`) reader 는 신뢰도 평가 분기 가능.

본 contract 는 spec 011 의 입력 권위로 작용한다. 본 PATCH 가 schema 를 바꾸면 spec 011 의 reader 가 회귀 — 그러나 본 PATCH 는 spec 013 의 기존 schema 를 그대로 보존하므로 회귀 위험 0.
