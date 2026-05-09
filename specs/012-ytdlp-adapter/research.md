# Phase 0 Research: yt-dlp 자막·음원·지문 어댑터

**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Spike**: `_workspace/spike/ytdlp_feasibility.md`

NEEDS CLARIFICATION 0건 — spike 측정 + clarify Q1~Q5 로 모든 unknowns 해소. 본 문서는 결정·근거·대안을 카탈로그.

---

## R-1. yt-dlp 호출 패턴 (자막)

**Decision**: `yt-dlp --cookies-from-browser brave --write-subs --write-auto-subs --sub-format srv3 --sub-langs "ko,ko-orig,ko.*" --skip-download --output ...` 단일 호출로 manual + auto 양쪽 트랙 다운로드. 후처리에서 manual 우선 fallback.

**Rationale**:
- `--write-subs` 와 `--write-auto-subs` 는 서로 다른 파일을 떨어뜨림 (`<vid>.ko.srv3` manual 또는 `<vid>.ko.srv3` auto + `<vid>.ko-orig.srv3` auto-original) — yt-dlp는 manual 존재 시 manual을 `<vid>.ko.srv3` 에 우선 할당.
- 단일 호출이 cookies 디크립션 1회만 발생 (시간 절약 + brave keyring 부하 감소).
- spike에서 `--write-auto-subs` 단독으로 두 트랙 (`ko`, `ko-orig`) 모두 142.74 KiB 동일 크기 다운로드 검증 — manual 없는 영상 시나리오.

**Alternatives considered**:
- 두 번 호출 (`--write-subs` 먼저, 결과 검사 후 부재 시 `--write-auto-subs`) — cookies 디크립션 2회, rate limit 압박 두 배.
- 단일 `--sub-langs ko` 만 — `ko-orig` 폴백 트랙 손실. 매뉴얼 없는 영상에서 fail.

**참고**: yt-dlp v2026.03.17 부터 `--sub-format srv3` 가 기본 우선순위로 처리됨 (XML 형식, 시간 기반 segment 직접 추출 가능).

---

## R-2. srv3 → spec 010 transcript JSON 변환 규칙

**Decision**: stdlib `xml.etree.ElementTree` 로 파싱, `<p t="ms" d="ms">` segment + `<s>` child text concat, `<p a="1">` ASR rolling-display는 skip.

**Rationale** (spike 검증):
- `<p>` 의 `a="1"` 속성은 ASR 한 word 추가 시 다음 chunk의 prefix를 미리 표시하는 rolling display — 다음 정상 `<p>` 에 동일 텍스트가 다시 나오므로 중복 방지를 위해 skip.
- `<s t="..." ac="...">` 의 `t` 는 부모 `<p>` 시작점 기준 word-level offset(ms) — spec 010 segment 단위에서는 word-level 시간이 불필요 (텍스트만 concat).
- segment.start = `p.t / 1000`, segment.end = `(p.t + p.d) / 1000`, text = `<s>` 텍스트 직선 결합.
- spike V1: 767 segments, start=3.3s, end=1982.3s vs audio=1989s (마지막 무음 7s 정상).

**Alternatives considered**:
- `srv1` (CSV-like) format — 더 간단하지만 yt-dlp `--sub-format srv1` 호환성 v2025+ 부터 보장.
- `vtt` (WebVTT) — pyVTT 라이브러리 추가 필요 + 시간 파싱 정밀도 ms→s 변환에서 0.001s 오차.
- `json3` (YouTube native) — 비공식 필드 다수, 형식 변경 위험.

**Edge cases handled**:
- 비어있는 `<p>` (whitespace only) → skip
- `<p>` text 직접 (no `<s>`) → 그대로 사용 (간혹 발생)
- 중복 segment timestamp → 그대로 보존 (spec 010이 dedup 책임 0)

---

## R-3. 음원 추출 yt-dlp 호출 패턴

**Decision**: `yt-dlp --cookies-from-browser brave --extract-audio --audio-format mp3 --audio-quality 128K --postprocessor-args "ffmpeg:-ar 22050 -ac 1" --output ...`

**Rationale**:
- 22050Hz mono mp3 128kbps 는 chromaprint 권장 입력 (acoustid.org "Submitting Fingerprints" 가이드).
- `ffmpeg:` prefix 강제 — spike에서 bare `-ar -ac` 시 yt-dlp WARN ("Post-Processor arguments given without specifying name") 발생 검증. ffmpeg 외 PP에 args 잘못 전달 방지.
- 단일 호출 — 동일 cookies, 동일 sleep window 내.

**Alternatives considered**:
- `--audio-format wav` — fpcalc 정확도 향상이나 파일 크기 ~10x → storage 부담. spike 측정 mp3 22050Hz mono 정확도 충분(self-hamming = 0).
- 44100Hz stereo — chromaprint는 내부적으로 11025Hz mono로 다운샘플링하므로 추가 정확도 0, 파일 크기 4x.
- `webm` 원본 그대로 fpcalc — fpcalc는 webm 입력 지원하지만 ffmpeg lib 버전 종속성. mp3로 표준화하여 향후 디버깅 일관성.

**Performance** (spike 측정):
- 33분 영상 → 17초 wall-clock (다운로드 7초 + ffmpeg 변환 10초)
- 28분 영상 → 12초 wall-clock
- 영상 1분당 ~0.5초 wall-clock (네트워크 + 변환 합산)

---

## R-4. chromaprint 지문 산출 — fpcalc subprocess 단일 경로

**Decision**: `subprocess.run(["fpcalc", "-length", "0", str(audio_path)], capture_output=True, text=True, check=False)` 호출, stdout에서 `DURATION=` / `FINGERPRINT=` 정규식 추출. **pyacoustid `fingerprint_file()` 사용 0**.

**Rationale** (spike 검증 + architecture 결정):
- pyacoustid `fingerprint_file()` 는 `audioread` 백엔드 의존 → NixOS 호스트에서 ffmpeg dynamic load 실패 시 `audioread.exceptions.NoBackendError` 빈번.
- fpcalc CLI는 ffmpeg 라이브러리를 자체 link (chromaprint 1.6.0 빌드는 statically-linked decoders 포함) → CLI 호출 시 외부 의존 0.
- subprocess timeout 설정 가능 (영상별 최대 30초 등), 진단 stderr 수집 용이.
- spike에서 V1/V2 양쪽 fpcalc < 1초 측정 (33분/28분 영상).

**Alternatives considered**:
- pyacoustid `fingerprint_file()` — 위 NoBackendError 사유로 제외.
- chromaprint c-API ctypes 직접 wrapping — 90줄 추가 코드 + 메모리 안전성 책임. 명확한 이득 없음.
- `librosa` + custom hash — chromaprint 호환 없음 → spec Y matching 알고리즘 재작성 필요. 큰 비용.

**Output 형식**:
- stdout: `FILE=...\nDURATION=NNNN\nFINGERPRINT=AQA...\n`
- 정규식: `^DURATION=(\d+)$` (line-anchored), `^FINGERPRINT=(\S+)$`
- b64 fingerprint 길이 ~2 KB/min (33분 → 65,455 bytes)

---

## R-5. chromaprint Python decode (similarity 단계)

**Decision**: pyacoustid PyPI 패키지 의존성 추가 (단 `chromaprint` 모듈 import만 사용). `chromaprint.decode_fingerprint(fp_b64.encode("ascii"))` → `(list[int], version)`.

**Rationale**:
- pyacoustid 패키지에는 두 가지 import: `acoustid` (audio decode + AcoustID 서비스 호출) 와 `chromaprint` (b64 decode/encode 순수 함수).
- 본 spec은 `chromaprint` 만 사용 — c-extension 가벼움 (libchromaprint.so 의존), audio decode 의존 0.
- numpy `np.array(ints, dtype=np.uint32)` 로 SIMD 가속 hamming 계산 가능 (`np.unpackbits` + XOR).

**LD_LIBRARY_PATH 요구사항** (NixOS, spike 검증):
- `libchromaprint.so` ← `nixpkgs#chromaprint`
- `libstdc++.so.6` ← `nixpkgs#stdenv.cc.cc.lib` (numpy c-ext 의존)
- `libz.so.1` ← `nixpkgs#zlib` (numpy 일부 build 의존)
- ffmpeg lib는 fpcalc statically-linked이므로 LD에 노출 불필요 (단, yt-dlp 의 audio extract 단계는 ffmpeg CLI 호출 — `nixpkgs#ffmpeg` PATH 필요)

**Alternatives considered**:
- chromaprint 패키지 단독 (PyPI에 별도 `chromaprint==N.N.N` 있음) — 그 패키지는 chromaprint 1.4 시절 wrapper로 내부 c-API 차이 있음. spike에서는 pyacoustid 동봉 모듈로 검증됨.
- numpy 미사용 pure-Python hamming — 16,045 ints × 8M pair = 너무 느림.

---

## R-6. cookies fallback chain (clarify Q3 결정)

**Decision** (clarify Q3 결정 → FR-017 반영):
1. CLI 명시 `--cookies-browser <name>` 또는 `--cookies-file <path>`
2. 디폴트 `--cookies-from-browser brave`
3. 환경변수 `TUBE_SCOUT_COOKIES_FILE` (agenix 적용 가능)
4. 디폴트 경로 `~/.config/tube-scout/cookies.txt` (0600)
5. 모두 부재 시 actionable 영문 메시지 + 명령 종료 (Constitution II)

**Rationale**:
- 운영자 1인 + 자기 백업 정당성 → cookies-from-browser 가장 간편.
- agenix 환경변수는 cron 환경(headless)에서 keyring locked 시 자동 폴백 enable.
- 디폴트 경로는 spec 009의 `~/.config/tube-scout/` 컨벤션과 일치 — 운영자 mental model 단순화.

**Security**:
- cookies.txt 파일 0600 강제 (생성 시 검증, 권한 약하면 actionable 거절)
- 환경변수 path가 `/tmp/` 또는 world-readable 디렉터리 가리키면 거절 (Constitution II 준수)
- `.gitignore` 에 `cookies.txt`, `**/cookies*.txt` 추가 (실수 commit 방지)

**Alternatives considered**:
- agenix `.age` 파일에 cookies 직접 저장 → 매 호출 decrypt 비용 + cookies 갱신 시 매번 agenix re-key. UX 부담 ↑.
- Brave 자동 unlock CLI (`secret-tool` 등) — 운영자 비밀번호 stdin 요구. cron 자동화 불가.

---

## R-7. rate limit 디폴트 + backoff

**Decision**: 
- 호출 간 sleep: random.uniform(30.0, 60.0) 초
- HTTP 429 발생 시 backoff: 60s → 300s → 1800s, 최대 3회
- 4번째 실패 시 채널 단위 종료 + audit-log "rate_limit_exhausted" + 다음 채널 진행

**Rationale**:
- spike 측정: sleep 0 으로 5분 내 6 cookies-인증 호출 / 429 0건 → 30s 안전 추정.
- jitter (30~60 random) — YouTube anti-scraping pattern 학습 회피.
- exponential backoff 60→300→1800 — 30분(1800s) 후에도 회복 안 되면 IP 차단 의심 → 즉시 종료 + 운영자 안내.

**Alternatives considered**:
- 고정 30s sleep — anti-scraping 패턴 인식 위험.
- 5s 짧은 sleep + 429 retry-heavy — IP reputation 손상 가능.
- 백그라운드 큐 + 분산 — 단일 운영자 환경 과잉 설계.

**Production validation**: dev-squad의 `tests/integration/test_ytdlp_rate_limit.py @pytest.mark.slow` 50-URL 시퀀스 측정 (운영자 결정 시 실행).

---

## R-8. SQLite v3 schema migration (B-X1-2)

**Decision**: spec 011 `content_reuse.db` v2 위에 `audio_fingerprint` 테이블 ALTER 추가. 기존 컬럼·테이블 변경 0.

**DDL** (data-model.md 에서 상세):
```sql
CREATE TABLE IF NOT EXISTS audio_fingerprint (
    video_id TEXT PRIMARY KEY,
    fingerprint BLOB NOT NULL,
    duration REAL NOT NULL,
    extracted_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'fpcalc:1.6.0',
    FOREIGN KEY (video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_audio_fp_extracted_at ON audio_fingerprint(extracted_at);

PRAGMA user_version = 3;
```

**Rationale**:
- `IF NOT EXISTS` 로 재실행 안전 (idempotent).
- `user_version = 3` 으로 schema version 추적 — `migrate_to_v3()` 진입 조건.
- FK ON DELETE CASCADE — videos 테이블에서 영상 삭제 시 지문 자동 정리 (운영자 수동 영상 제거 시).
- `source` 필드 — 향후 fpcalc 버전 차이 / 다른 알고리즘(spec Y에서 LSH bucket id 등) 도입 시 forward compat.

**Alternatives considered**:
- 별도 SQLite 파일 (`audio_fingerprint.db`) — JOIN 비용 ↑, 운영자 관리 파일 ↑. spec 011 단일 DB 정책과 충돌.
- video_id 외 추가 PK (예: `(video_id, source)` compound) — 동일 영상 여러 알고리즘 지원 위해 좋으나 현재 spec X1은 fpcalc 단일 → YAGNI.

**Migration test**: `test_content_db_v3.py` — 빈 DB → v2 migrate → v3 migrate → audio_fingerprint INSERT/SELECT → re-run migrate (idempotent 확인) → v2 row 영향 0 확인.

---

## R-9. CLI 명령 + 환경변수 (B-X1-7 + clarify Q4/Q5)

**Decision**:

```text
tube-scout collect transcripts [--source {api|ytdlp}] [--channel <alias> | --all-channels] [--force]
tube-scout collect audio       [--channel <alias> | --all-channels] [--force]
tube-scout collect fingerprint [--channel <alias> | --all-channels] [--force]
```

**환경변수 우선순위** (clarify Q3 + Q4):
- `TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE` (api / ytdlp) — clarify Q4
- `TUBE_SCOUT_COOKIES_FILE` (file path) — clarify Q3
- `TUBE_SCOUT_COOKIES_BROWSER` (brave / firefox / ... — 선택) — yt-dlp `--cookies-from-browser` 디폴트 변경

**Rationale**:
- `--all-channels` 와 `--channel <alias>` 상호 배타 (둘 다 누락 시 actionable 거절).
- 환경변수는 `.envrc` (direnv) 또는 cron MAILTO 위에 1줄로 설정 — 운영자 단일 토글 지점.
- `--force` 는 idempotent skip 우회 (dev-squad 테스트용 + 운영자 재추출 시).

**Alternatives considered**:
- `tube-scout backfill --all` 메가 명령 — 단계별 실패 처리 복잡도 ↑, 진단 어려움.
- 환경변수 대신 config 파일 — 운영자 입장에서 cron 시 `.envrc` 활성화 vs config 경로 명시 — 환경변수가 더 단순.

---

## R-10. flake.nix devShell 패치 (B-X1-8)

**Decision**: `flake.nix` `devShells.default.buildInputs` 에 5건 추가 + `shellHook` 에 `LD_LIBRARY_PATH` export.

**Patch (Plan 단계 spec, 실제 적용은 dev-squad)**:
```nix
buildInputs = with pkgs; [
  python311
  # ... 기존 ...
  yt-dlp           # NEW — caption + audio fetch
  chromaprint      # NEW — fpcalc CLI + libchromaprint.so
  ffmpeg-full      # NEW (또는 기존 ffmpeg가 있으면 그대로) — yt-dlp postprocessor
  zlib             # NEW — numpy c-ext LD
  stdenv.cc.cc.lib # NEW — libstdc++ LD
];

shellHook = ''
  export LD_LIBRARY_PATH="${pkgs.chromaprint}/lib:${pkgs.zlib}/lib:${pkgs.stdenv.cc.cc.lib}/lib:''${LD_LIBRARY_PATH}"
'';
```

**Rationale**:
- spike에서 4개 LD 의존성 모두 검증 (numpy 2.4.4 import 성공).
- shellHook 으로 자동 export — 운영자 수동 설정 0.
- 기존 `LD_LIBRARY_PATH` 보존 (덮어쓰기 0).

**Alternatives considered**:
- nix-ld — nix-ld는 시스템 단위 설정 (NixOS module), devShell 단위 격리 불가.
- 사용자가 매 명령마다 LD env export — 운영자 부담, cron 환경에서 잊기 쉬움.

---

## R-11. Audit CSV 형식 동결 (B-X1-7)

**Decision**: CSV 컬럼 sequence 동결, 파일 별 schema:

`transcripts_audit.csv`:
```
video_id,result,reason,source,timestamp,cookies_source
```

`fingerprint_audit.csv`:
```
video_id,result,reason,duration_sec,timestamp,cookies_source
```

**값 영역**:
- `result`: success | skip | fail
- `reason` (자막): captured | skip_existing | no_captions_available | rate_limit | cookies_expired | live_or_premiere | network_failure | interrupted
- `reason` (지문): captured | skip_existing | too_short | audio_decode_failed | fpcalc_failed | rate_limit | interrupted
- `source` (자막만): ytdlp:manual | ytdlp:auto | api
- `cookies_source`: brave | file | n/a

**Rationale**:
- 운영자 컴플라이언스 검증용 — 기존 audit CSV 컨벤션 (spec 009 transcripts_audit.csv) 와 컬럼 이름 정합.
- 작은 schema 차이 (자막 source vs 지문 duration_sec) — 두 stage의 의미가 다름.
- pandas/polars 로 빠른 grouping 가능 (`result.value_counts()` 등).

**Alternatives considered**:
- 단일 통합 CSV — stage 컬럼 추가 + reason vocabulary 두 배. 분석 복잡.
- JSON-Lines — 컬럼 sparsity OK, 그러나 spec 009 CSV 컨벤션 정합 우선.

---

## 관련 메모 / 외부 참조

- AcoustID 가이드 — chromaprint 권장 입력: 22050Hz mono PCM, 길이 ≥ 30초, 정확도 위해 ≥ 120초 권장 (본 spec은 30초 이상 모두 처리, spec Y가 정밀도 확보 책임).
- yt-dlp Wiki: cookies-from-browser 호환 브라우저 — Brave는 v2025.10+ 부터 공식 지원 (Chromium 기반이므로 chromium decryption 로직 재사용).
- spec 011 commit `e6d92d2` — INTEGRATION wire report content CLI (본 spec 변경 없이 호환 보장).
- 메모리 `project_data_acquisition_strategy` — yt-dlp 운영 모델, v0.4~v1.0 로드맵.
- 메모리 `feedback_runtime_integration_gaps` D-13~D-17 — boundary 결함 학습, 본 spec §Cross-Spec Boundaries 9개로 사전 예방.
