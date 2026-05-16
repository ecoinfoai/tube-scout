# idea spec 018: unified_ingest 영구화 + 멱등 가드 (spec 017 PATCH)

> **진입 명령**: 새 세션에서 `/speckit.specify` 호출 시 본 파일을 시드로 사용한다. 사용자 결정 (2026-05-16): "specify 를 새로 해서 수정".

## 발견 경위 (2026-05-16, T043 walkthrough 실측)

spec 017 의 `tube-scout collect ingest` 통합 명령의 T043 walkthrough 두 번째 호출에서 SC-004 멱등 부분 실패가 식별되었다. 한 사이클 14m36s 가 자막 ASR 재처리에 소요되어, 22 학과 운영 시 재호출마다 14m36s × 22 = 약 5 시간 24 분 의 누적 낭비를 초래한다.

### 실측 결과 (간호학과 archive, RTX 3060 + 표준 PC, archive 9.9 GB / 9 mp4 / 메타 2554)

| 호출 회차 | wall clock | 자막 결과 | 지문 결과 | 매니페스트 | 비고 |
|---|---|---|---|---|---|
| 1 (T037 측정, libcublas 미설치) | ~64s | 0✓/9✗ | 9✓ | 9 추가 | libcublas.so.12 누락으로 자막 실패 |
| 2 (cuBLAS 정비 후 fresh) | 14m37s (877.4s) | 9✓/0✗ | 9✓ | 0 추가 / 9 해소 | 우선 재시도로 9 entries 해소 |
| 3 (멱등 회귀 검증) | **14m36s (875.3s)** ❌ | 9✓/0✗ (재처리) | 9✓ (재처리) | 0 추가 / 0 해소 | **SC-004 위반** |

3 회차의 875.3s 는 quickstart §5 항목 3 의 "자막·지문 재생성 0" 약속을 위반한다. `new=0` (DB 영상 행 신규 0) 만 통과하고, 자막/지문 재처리는 매번 발생한다.

## 3 결함 (코드 위치 + 증상)

### 결함 A — ASR 결과 휘발

- **위치**: `src/tube_scout/services/unified_ingest.py:100`
- **현재 코드**: `transcribe_audio(wav_path); transcript_successes += 1`
- **결함**: `transcribe_audio` 의 반환값 (`TranscribeResult` — `segments` / `language_detected` / `duration` / `asr_quality_flags` / `caption_source_detail`) 을 받지 않고 폐기. 자막 텍스트가 디스크 / DB 어디에도 저장되지 않는다.
- **실측 증거**: `find data/nursing -name "*.json"` 결과가 빈 (자막 json 파일이 아예 생성 안 됨, 02_analyze/ 디렉토리 자체도 없음).

### 결함 B — 지문 결과 휘발

- **위치**: `src/tube_scout/services/unified_ingest.py:113`
- **현재 코드**: `extract_chromaprint_fingerprint(wav_path); fingerprint_successes += 1`
- **결함**: 반환값 `(fp_b64_bytes, duration_seconds)` 을 폐기. `audio_fingerprint` DB 테이블에 row 가 추가되지 않는다 (spec 013 schema 의 의도 위반).

### 결함 C — 멱등 가드 부재

- **위치**: `src/tube_scout/services/unified_ingest.py:72` for loop
- **현재 코드**: `for mp4_path_str, video_id in mp4_video_id_map.items():` 후 무조건 WAV 추출 + ASR + 지문 처리
- **결함**: 이미 처리된 영상에 대한 skip 조건이 전무. 처리 결과를 어디에도 저장하지 않기에 (결함 A·B), 가드를 둘 곳 자체가 없는 구조적 부작용.

## 표준 fix 패턴 (코드베이스에 이미 존재 — 복사하여 적용)

### 지문 영구화 + 멱등 가드 — `cli/collect.py:1931-1956` (`collect_fingerprint_command`)

```python
# 1) 멱등 가드 (DB SELECT)
if not force:
    with sqlite3.connect(db) as conn:
        existing = conn.execute(
            "SELECT 1 FROM audio_fingerprint WHERE video_id = ?",
            (video_id,),
        ).fetchone()
    if existing:
        audit.append_fingerprint_row({"reason": "already_fingerprinted", ...})
        continue

# 2) 영구화
fp_bytes, duration = extract_chromaprint_fingerprint(input_path)
insert_audio_fingerprint(db, video_id, fp_bytes, duration, ts)
```

### 자막 영구화 — `cli/collect.py:2250-2295` (`process-audio` 통합 모드)

```python
asr_result = transcribe_audio(wav_path, ...)
transcript = {
    "video_id": video_id,
    "source": asr_result.caption_source_detail,
    "language": asr_result.language_detected,
    "duration": asr_result.duration,
    "segments": asr_result.segments,
    "asr_quality_flags": asr_result.asr_quality_flags.model_dump(),
    "fetched_at": ts,
}
json_path = transcript_dir / f"{video_id}.json"
# tempfile.mkstemp + os.replace 로 atomic write
```

자막 영구화 위치 표준: `data/<alias>/02_analyze/transcripts/<video_id>.json` (spec 013 의 `collect transcripts` 출력 경로와 동일 — 분리 명령과 통합 명령의 산출물 위치 일관성 보존).

## ✅ 완료 (2026-05-16 구현 closure)

spec 018 전체 구현 완료. Phase 1~6 (T001~T050) 커밋 완료. branch `018-ingest-persist-idempotent`.

---

## spec 018 범위 (FR 후보 — `/speckit.specify` 에서 확정)

### MUST FR

- **FR-018A — ASR 결과 영구화**: `_run_transcript_and_fingerprint` 가 `transcribe_audio` 반환값을 `data/<alias>/02_analyze/transcripts/<video_id>.json` 에 atomic write (`tempfile.mkstemp` + `os.replace`). 직렬화 schema 는 spec 013 의 `collect transcripts` 출력 schema 와 동일 (video_id / source / language / duration / segments / asr_quality_flags / fetched_at).
- **FR-018B — 지문 영구화**: `_run_transcript_and_fingerprint` 가 `extract_chromaprint_fingerprint` 반환값을 `insert_audio_fingerprint(db, video_id, fp_bytes, duration, ts)` 로 영구화. spec 013 의 `audio_fingerprint` 테이블 schema 보존.
- **FR-018C — 멱등 가드**: 영상별 처리 진입 전 두 단계 가드:
  - 자막: `(transcript_dir / f"{video_id}.json").exists()` 시 skip + audit `reason=already_transcribed`
  - 지문: `SELECT 1 FROM audio_fingerprint WHERE video_id = ?` 시 skip + audit `reason=already_fingerprinted`
- **FR-018D — `--force` flag**: 멱등 가드 우회하여 강제 재처리. `cli/collect.py::collect_ingest_command` 에 `--force` 옵션 추가 (spec 013 `collect_fingerprint_command` 시그니처와 일관).

### SHOULD FR

- **FR-018E — WAV 추출 자체 skip**: 자막과 지문 둘 다 멱등 skip 된 영상은 WAV 디코딩 자체를 skip (SC-005 의 "1 회 디코딩" 약속이 멱등 흐름에서도 보존, 즉 멱등 호출 시 디코딩 0 회).
- **FR-018F — 회귀 매트릭스 강화**: `tests/integration/test_ingest_idempotent.py` 를 mock 환경뿐 아니라 실제 archive fixture 회귀로 보강하여 자막 json 파일 mtime + `audio_fingerprint` 테이블 row count 모두 검증. T013 시점의 mock-only 검증 한계를 청산.

### Acceptance (Success Criteria 후보)

- **SC-018-1 (SC-004 회복)**: 같은 archive 두 번째 호출의 통합 명령 wall clock ≤ 2 초 (멱등 hot path), Rich Table 의 자막/지문 단계 "성공: 0 / 실패: 0 / 소요 시간: <1s" (또는 명시적 "skip" 행 추가), 매니페스트 0 추가 / 0 해소.
- **SC-018-2**: 첫 호출 종료 시점에 자막 json 9 개가 `data/<alias>/02_analyze/transcripts/<video_id>.json` 에 atomic write 되어 있고, `audio_fingerprint` 테이블에 video_id 9 개의 row 가 영구화되어 있다.
- **SC-018-3**: `--force` 옵션 사용 시 멱등 가드를 우회하여 자막/지문 모두 재처리 (wall clock 약 14m36s).

## 작업 진입 흐름 (사용자 결정 — 2026-05-16)

1. `/speckit.specify` 호출 — 본 idea 파일이 자동 시드
2. `/speckit.plan` → `/speckit.tasks` → `/speckit.analyze` 표준 흐름
3. implementation 진입 방식 = 사용자 선택 (dev-squad 재소집 또는 `/speckit.implement` 또는 lead 단독)
4. pyproject 버전: 현재 `0.6.0.dev0` 유지 → spec 018 PATCH 완료 후 0.6.0 final 또는 0.6.1 결정

## 입력 시드 / 참고 자료

- `_workspace/spec017_t037_runs.log` — 1 회차 측정 raw
- `_workspace/spec017_baseline_after_memoize.md` — 1~2 회차 분석 + T037/T041/T042/T043/T044 closure 요약
- spec 017 quickstart §5 KNOWN LIMITATION 항목 (2026-05-16 단일 commit 시도, 외부 수정 충돌로 본 세션 미적용 — spec 018 spec.md 에서 quickstart 갱신 일괄 처리)
- spec 013 standard pattern 위치 2 곳: `cli/collect.py:1931-1956` + `cli/collect.py:2250-2295`

## 본 idea 의 작성 배경 (사용자 신호)

본 세션 (2026-05-16) 종결 시점에 사용자가 "5 시간 ratelimit 의 5% 를 1 분도 안 되어 사용" 한 점을 토대로 본 세션을 즉시 종결하고, 새 세션이 `/speckit.specify` 1 회로 모든 컨텍스트를 흡수할 수 있도록 본 단일 시드를 영구화한다. 새 세션 lead 는 본 파일 1 read 외 추가 코드/로그 read 가 불필요 — 모든 위치와 패턴이 본문에 인용되어 있다.
