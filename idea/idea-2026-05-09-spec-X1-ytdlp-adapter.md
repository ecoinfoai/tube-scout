# spec X1 — yt-dlp 자막·음원·지문 어댑터 (spike-first 진행)

**작성일**: 2026-05-09
**상태**: **spike 통과 (2026-05-09)** — `/speckit.specify` 진입 준비 완료. spike 결과 → `_workspace/spike/ytdlp_feasibility.md`
**spike 정의**: XP 용어로 "기술적 불확실성을 짧은 time-box(45분)에 해소하는 탐색 검증". 산출물은 폐기 전제, feasibility 5가지에만 답. (pilot test 와 다름 — pilot 은 축소 production 운영)
**선행**: spec 007 (재사용 탐지), spec 010 (`--prefer-captions-api` + skip-existing — 직전 머지), spec 011 (자막 풀스택 nC2 — branch `011-reuse-fullstack-subtitle` 35 commits 완료)
**계기**: 2026-05-09 세션에서 운영자(DX센터장)와 합의 — YouTube Data API quota 승인 1~3 영업일 대기 중. spec 010의 OAuth Captions API 경로가 quota 의존이라 22채널 × ~4,000 영상 백필 진행 불가. yt-dlp + cookies-from-browser로 우회 + 음향 지문(roadmap §3 spec Y) 동시 도입 path C 검토.

---

## Executive Summary

세 줄 요약:

1. **yt-dlp adapter를 tube-scout 안에 모듈로 통합** — 별도 프로젝트 분리 No, 벤더링/클론 No, pip 의존성 + `services/ytdlp_adapter.py` 어댑터 한 모듈.
2. **spike(탐색 검증) 통과 (2026-05-09)** — 일부공개 + 비공개 영상 양쪽에서 brave cookies-from-browser 디크립션 정상, srv3→spec 010 JSON 무손실 변환, 33분 영상 음원·지문 17초 wall-clock, V1↔V2 cross-hamming 47% (다른 강의 → 거의 random) 로 음향 매칭 가설 1차 입증.
3. **roadmap path C 가속 가능** — spike에서 chromaprint similarity가 명확히 분리되어 spec X1 (yt-dlp) + spec Y (음향 지문) v0.4 동시 출시 검토 가능. 단, 동일 강의자 baseline(intro/outro 공통 반복) 추가 spike 1회 권장.

---

## §1. 본 spec의 목적

### 1.1 해결하려는 문제

| 문제 | 영향 | 본 spec 해결 |
|---|---|---|
| YouTube Data API quota 승인 지연 | 22채널 자막 백필 막힘 | yt-dlp 우회 (quota 0 사용) |
| 비공개 영상 88.6% (~3,544 영상) | youtube-transcript-api 단독 불가 | yt-dlp + `cookies-from-browser` (운영자 본인 인증) |
| 자막 부재 영상 ~24개 | spec 011 Q-001 fail로 분석 불가 | 음향 지문 (chromaprint) — 자막 없어도 매칭 가능 |
| 같은 슬라이드 다른 음성 (재녹음) | 자막 비슷 → false positive | 음향 지문 다름 → 정상 판정 |

### 1.2 본 spec이 **하지 않는** 일

- 영상 자체 영구 보관 — 추출 후 즉시 폐기 (roadmap §5.3 임시 계층)
- 외부 채널 분석 — 자교 22채널 전용 (PS-A-12 영구 scope OUT)
- DTW 속도 변화 대응 — v0.8 미래 spec
- OCR / 화자 분리 — 영구 scope OUT

---

## §2. 통합 결정 — 별도 프로젝트 분리 No

운영자와 합의한 architecture decision:

| 옵션 | 결정 |
|---|---|
| (a) yt-dlp 소스 클론/벤더링 | ❌ **No** — 매주 update 필요, 보안 패치 누락 위험 |
| (b) yt-dlp pip dep + 어댑터 모듈 | ✅ **Yes** — 본 spec 채택 |
| (c) 별도 repo `tube-scout-acquire` | ❌ **No** — 단일 운영자 환경에서 boundary 비용 두 배 |

**(b) 선택 근거 5가지**:
1. 단일 운영자 (DX센터장 1인) — 도구 둘이면 cron + 디버깅 두 배.
2. Constitution VII 누적 학습 (`feedback_runtime_integration_gaps` D-13~D-17) — inter-project boundary는 위험.
3. spec 010 의 `--prefer-captions-api` dispatching 패턴 그대로 확장 (`--source ytdlp`).
4. 실패 격리는 모듈 한 칸 (`services/ytdlp_adapter.py` 안의 try/except)으로 충분.
5. 외부 채널 모니터링 0건 — 다른 프로젝트 재사용 가능성 0.

---

## §3. Spike 우선 — 정식 spec 전 30~45분 검증

### 3.1 왜 spike 먼저?

`/speckit.specify` 시 시그니처를 추정으로 작성 → 작업 중 yt-dlp 실제 동작이 다르면 spec 재작업. 비용 큼. spike으로 다음 5가지를 실측 데이터로 확정:

- yt-dlp `srv3` 출력 → spec 010 `transcripts/{vid}.json` 형식 변환 정확 명세
- 음원 추출 시간 (영상 1분당 wall-clock 몇 초)
- chromaprint 지문 크기 + Python decode 형식
- 비공개 영상 `cookies-from-browser` 실제 작동 여부
- Rate limit 트리거 임계 (5영상 30s sleep 연속 시도)

### 3.2 Spike 입력 (운영자 → 다음 세션)

```
TEST_URL_FIRST=https://www.youtube.com/watch?v=<VID_1>      # 일부공개 또는 공개
TEST_URL_PRIVATE=https://www.youtube.com/watch?v=<VID_2>    # 비공개 (cookies 검증용)
TEST_COOKIES_BROWSER=brave                                  # brave|chrome|chromium|edge|firefox|opera|vivaldi|whale
```

**채널 visibility 분포 메모** (자교 간호학과 기준):
- 공개 (Public): 0% (없음)
- 일부공개 (Unlisted): ~6~11%
- 비공개 (Private): ~88.6%

→ 공개 영상이 없는 상태가 production 시나리오 그대로. spike의 두 영상은 **일부공개 1개 + 비공개 1개** 권장. 일부공개도 처음부터 cookies 흐름으로 검증 (production cron은 모든 영상에 cookies 적용 단일 path).

**`VID_1` (일부공개) 선정 기준**:
- 1~5분 길이 (spike 시간 보호)
- 자교 간호학과 채널 (ToS — 자기 백업 정당성)
- 한국어 ASR 자막 있음 (spec 010 형식 검증)
- 강의/공지/캠퍼스 소식 클립 (음악·외부 콘텐츠 회피)

**`VID_2` (비공개) 선정 기준**:
- 같은 채널, 같은 길이대 (1~5분)
- 운영자 본인이 채널 owner로 cookies 인증 가능

**피해야 할 영상**:
- live stream / premiere (finalized 안 됨)
- 30초 미만 (chromaprint 지문 unreliable)
- 2시간 초과 (spike 시간 낭비)
- 외부 채널 (ToS 위반)
- 음악 video (다운로드 차단 가능성)

**Brave + NixOS 주의** (Step 2 영향):
- Brave는 cookies SQLite를 disk에 저장하지만 일부 필드를 libsecret/gnome-keyring으로 암호화
- yt-dlp의 `--cookies-from-browser brave`는 keyring unlock 상태에서만 정상 동작
- keyring locked 상태면 디크립션 실패 → fallback: Brave 확장 "Get cookies.txt LOCALLY" 등으로 cookies.txt export → `--cookies /path/to/cookies.txt`
- spike Step 2가 두 path 모두 검증 (cookies-from-browser 우선, 실패 시 cookies.txt)

### 3.3 Spike Runbook (다음 세션 메인 세션이 직접 실행)

#### Step 0 — 환경 준비

```bash
cd /home/kjeong/localgit/tube-scout
mkdir -p /tmp/spike-ytdlp _workspace/spike

# Nix 격리 shell (tube-scout 환경 변경 0)
nix shell nixpkgs#yt-dlp nixpkgs#chromaprint nixpkgs#ffmpeg
which yt-dlp fpcalc ffmpeg  # 셋 다 PATH에 보여야 함
yt-dlp --version            # 버전 기록 (spec X1 의존성에 명시 예정)
fpcalc -version
```

#### Step 1 — 자막 fetch (일부공개 영상, cookies 사용)

```bash
yt-dlp \
  --cookies-from-browser "$TEST_COOKIES_BROWSER" \
  --write-auto-subs \
  --sub-format srv3 \
  --sub-langs "ko,ko-orig,ko.*" \
  --skip-download \
  --output "/tmp/spike-ytdlp/%(id)s.%(ext)s" \
  "$TEST_URL_FIRST"

# 결과 확인
ls -la /tmp/spike-ytdlp/*.srv3
# srv3는 XML 형식 — 파싱 가능 여부 확인
head -50 /tmp/spike-ytdlp/*.srv3
```

**검증 항목**:
- [ ] srv3 파일 1개 이상 생성됨
- [ ] 한국어 segment text 추출 가능
- [ ] timestamp(start/end) 정확
- [ ] spec 010 `{video_id, segments: [{start, end, text}]}` 형식으로 변환 시 손실 없음

**`--cookies-from-browser brave` 실패 시 fallback** (NixOS keyring locked 등):
```bash
# Brave 확장 "Get cookies.txt LOCALLY" 또는 동등으로 cookies.txt export 후
yt-dlp \
  --cookies /tmp/spike-ytdlp/cookies.txt \
  --write-auto-subs --sub-format srv3 ... \
  "$TEST_URL_FIRST"
```
→ 둘 중 어느 path가 본 환경에서 작동하는지 spike에서 결정. spec X1에서 디폴트 + fallback 정책 확정.

#### Step 2 — 자막 fetch (비공개 영상, cookies 검증 핵심)

```bash
# cookies-from-browser brave 시도
yt-dlp \
  --cookies-from-browser brave \
  --write-auto-subs \
  --sub-format srv3 \
  --sub-langs "ko,ko-orig,ko.*" \
  --skip-download \
  --verbose \
  --output "/tmp/spike-ytdlp/%(id)s.%(ext)s" \
  "$TEST_URL_PRIVATE"

# verbose 로그에서 다음 확인:
# - "Extracting cookies from brave" 메시지
# - "Decrypted N cookies" 메시지 (libsecret/keyring 작동 확인)
# - HTTP 200 + 자막 다운로드 성공
```

**검증 항목**:
- [ ] cookies-from-browser brave keyring 디크립션 성공
- [ ] 비공개 영상에서 인증 거절 없이 srv3 다운로드 성공
- [ ] 일부공개(Step 1)와 비공개(Step 2)가 같은 cookies 흐름으로 작동

**fallback** (cookies-from-browser brave 실패 시):
```bash
# Brave에 cookies.txt 확장 설치 → youtube.com에서 Export → cookies.txt 저장
yt-dlp \
  --cookies /tmp/spike-ytdlp/cookies.txt \
  --write-auto-subs --sub-format srv3 ... \
  "$TEST_URL_PRIVATE"
```

**spike 결과로 결정할 것**:
- spec X1에서 cookies-from-browser brave 디폴트로 채택할지
- 또는 cookies.txt 파일을 디폴트로 운영하고 cookies-from-browser는 옵션으로 둘지
- agenix 통합 방식 (cookies.txt 경로를 환경변수로 받기)

#### Step 3 — 음원 추출

```bash
yt-dlp \
  --cookies-from-browser brave \
  --extract-audio \
  --audio-format mp3 \
  --audio-quality 128K \
  --postprocessor-args "-ar 22050 -ac 1" \
  --skip-download false \
  --output "/tmp/spike-ytdlp/%(id)s.%(ext)s" \
  "$TEST_URL_FIRST"

# 결과 확인
ls -la /tmp/spike-ytdlp/*.mp3
ffprobe /tmp/spike-ytdlp/*.mp3 2>&1 | grep -E 'Duration|Stream'
```

**검증 항목**:
- [ ] mp3 파일 생성, 22.05kHz mono 확인
- [ ] duration이 영상 길이와 일치
- [ ] 파일 크기 정상 (~58MB/hour @ 128kbps mono)
- [ ] 영상 1분당 wall-clock 다운로드 시간 기록

#### Step 4 — chromaprint 지문 산출

```bash
# CLI 산출
fpcalc -length 0 /tmp/spike-ytdlp/*.mp3
# 출력: DURATION=NN, FINGERPRINT=AQADtFI...

# 결과 텍스트 파일 보존
fpcalc -length 0 /tmp/spike-ytdlp/*.mp3 > /tmp/spike-ytdlp/fp_test1.txt
wc -c /tmp/spike-ytdlp/fp_test1.txt
```

**검증 항목**:
- [ ] FINGERPRINT 산출 성공
- [ ] 지문 크기 (영상 1분당 KB) 측정
- [ ] DURATION 값이 ffprobe 결과와 ±1초 일치

#### Step 5 — Python decode + similarity

```bash
# pyacoustid 임시 설치 (uv venv tmp)
uv run --with pyacoustid python -c "
import acoustid, chromaprint
import numpy as np

duration1, fp_b64 = acoustid.fingerprint_file('/tmp/spike-ytdlp/<vid>.mp3')
print(f'duration={duration1}s, fp_size={len(fp_b64)}B')

# Decode
ints, version = chromaprint.decode_fingerprint(fp_b64)
print(f'fp_int_count={len(ints)}, version={version}')

# Self-similarity (같은 영상 vs 자기 자신)
arr = np.array(ints, dtype=np.uint32)
xor_self = arr ^ arr
hamming_self = np.unpackbits(xor_self.view(np.uint8)).sum() / len(arr)
print(f'self-hamming={hamming_self:.3f} (expected: 0.0)')

# 만약 두 영상 있으면 cross-similarity
# ...
"
```

**검증 항목**:
- [ ] pyacoustid + chromaprint Python binding 작동
- [ ] decode 결과가 정수 list (uint32)
- [ ] self-hamming = 0 (같은 영상)
- [ ] (선택) 두 영상 cross-hamming 산출

#### Step 6 — Rate limit 검증 (cookies 사용)

```bash
# 5 영상 URL 준비 — 일부공개·비공개 섞어도 무방
URLS=(
  "https://www.youtube.com/watch?v=VID_A"
  "https://www.youtube.com/watch?v=VID_B"
  "https://www.youtube.com/watch?v=VID_C"
  "https://www.youtube.com/watch?v=VID_D"
  "https://www.youtube.com/watch?v=VID_E"
)
for url in "${URLS[@]}"; do
  yt-dlp \
    --cookies-from-browser brave \
    --write-auto-subs --skip-download --sub-format srv3 \
    --output "/tmp/spike-ytdlp/%(id)s.%(ext)s" \
    "$url"
  sleep 30
done
# 5번째까지 정상 완료 → 30s sleep 안전선 1차 검증
```

**검증 항목**:
- [ ] 5/5 영상 자막 다운로드 성공
- [ ] HTTP 429 / 차단 없음
- [ ] 한 영상당 평균 wall-clock 측정
- [ ] 운영자가 5 영상 추가 URL 미리 준비 (선택 — Step 1/2의 2 영상 + 추가 3 영상)

### 3.4 Spike 산출 (2026-05-09 실측)

전체 보고서: `_workspace/spike/ytdlp_feasibility.md` (261줄). 입력: `TEST_URL_FIRST=https://youtu.be/tuxscjwiJYs` (일부공개 33분), `TEST_URL_PRIVATE=https://youtu.be/LmfXiOJCIV8` (비공개 28분), `TEST_COOKIES_BROWSER=brave`.

**환경**:
- yt-dlp 2026.03.17 / chromaprint 1.6.0 / ffmpeg 8.0.1 (`nix shell` 격리, 호스트 PATH 무영향)

**Step 1 — 자막 fetch (일부공개)**: ✅ PASS
- brave cookies 922개 디크립션 성공, ko/ko-orig srv3 142.74 KiB 다운로드
- srv3 → spec 010 transcript JSON 변환 무손실 (767 segments, 3.3s ~ 1982.3s 커버)
- 파싱 규칙 확정: `<p a="1">` ASR rolling-display는 skip, 나머지는 `<s>` 텍스트 concat

**Step 2 — 자막 fetch (비공개, cookies 핵심 검증)**: ✅ PASS
- 비공개 영상도 동일 cookies 흐름으로 인증 거절 없이 다운로드 (725 segments, 1690s 커버)
- 일부공개·비공개 단일 path 검증 → production cron 단순화 가능
- fallback (cookies.txt) 검증 불필요 — brave keyring 이 본 환경에서 안정 작동

**Step 3 — 음원 추출**: ✅ PASS
- V1 (33분) → 17초 wall-clock, V2 (28분) → 12초 wall-clock (~0.5초/분)
- 22050Hz mono mp3 128kbps, ffprobe duration 정확 일치
- **주의**: `--postprocessor-args "ffmpeg:-ar 22050 -ac 1"` 형식 (ffmpeg: prefix 미사용 시 WARN 발생)

**Step 4 — chromaprint 지문**: ✅ PASS
- DURATION 일치 (V1: 1989, V2: 1691), 지문 크기 ~2 KB/min (b64)
- fpcalc wall-clock < 1초
- 22채널 × 4,000 영상 × 평균 25분 ≈ **5.5 GB SQLite 단일 파일 예상**

**Step 5 — Python decode + similarity**: ✅ PASS
- `chromaprint.decode_fingerprint()` → uint32 array, 8.07 ints/sec (chromaprint frame rate)
- self-hamming = 0 (sanity)
- **V1 vs V2 cross-hamming = 47.0%** @ best alignment (offset +35.7s) — 다른 강의 → near-random, 분리 능력 입증
- **architecture 결정**: pyacoustid `fingerprint_file()` 는 audioread 백엔드 의존 → NixOS 호스트에서 `NoBackendError` 빈번. **`subprocess(fpcalc)` 단일 경로 채택** (chromaprint Python 모듈은 decode 전용으로만 사용)

**Step 6 — Rate limit**: ⚠ PARTIAL
- 운영자 추가 5 URL 미제공 → 정식 5×30s sleep 시퀀스 미실행
- 그러나 spike 5분 내 채널당 6회 cookie-인증 호출 / sleep 0 / 차단 0 — 30s sleep 디폴트 안전 추정
- 정식 검증은 spec X1 dev-squad의 `tests/integration/test_ytdlp_rate_limit.py @pytest.mark.slow` 로 위임 (production 50+ URL × 30s sleep 시퀀스, 운영자 결정에 따름)

**총 spike 결론**: 5/6 PASS + 1 PARTIAL → spec X1 specify 진입 가능. 디폴트 결정 사항은 §4.2에 반영.

---

## §4. Spike 통과 후 spec X1 정식 scope (사전 sketch)

spike 결과로 시그니처 확정 후 정식 작성. 현재는 "예정 scope" 수준.

### 4.1 SCOPE (예상)

**신규 파일**:
- `src/tube_scout/services/ytdlp_adapter.py` (NEW)
- `src/tube_scout/services/srv3_parser.py` (NEW — srv3 → spec 010 transcript JSON)
- `src/tube_scout/services/audio_fingerprint.py` (NEW — fpcalc CLI 호출 wrapper)
- `tests/contract/test_ytdlp_adapter_contract.py` (NEW)
- `tests/unit/test_srv3_parser.py` (NEW)
- `tests/unit/test_audio_fingerprint.py` (NEW)
- `tests/integration/test_ytdlp_caption_flow.py` (NEW)
- `tests/integration/test_audio_fingerprint_flow.py` (NEW)

**수정 파일**:
- `src/tube_scout/cli/collect.py` (MODIFY)
  - `tube-scout collect transcripts --source {api|ytdlp}` (default: api → spec 010 호환)
  - `tube-scout collect audio --channel <alias> [--sleep-min 30 --sleep-max 60]` (NEW)
  - `tube-scout collect fingerprint --channel <alias>` (NEW — 음원 → 지문 → DB → 음원 폐기)
- `src/tube_scout/storage/content_db.py` (MODIFY)
  - `audio_fingerprint` 테이블 추가 (video_id PK, fingerprint BLOB, duration REAL, extracted_at)
  - migration: spec 011 v2 schema 위에 v3 추가
- `pyproject.toml` (MODIFY): `yt-dlp = "..."`, `pyacoustid = "..."`
- `flake.nix` (MODIFY): `chromaprint`, `ffmpeg-full` 추가

### 4.2 시그니처 (spike 결과 반영, 2026-05-09 확정)

본 시그니처는 spike 실측으로 확정 — 분리 가능한 4 모듈 구조. `pyacoustid.fingerprint_file()` 의존 제거, fpcalc CLI subprocess 단일 경로.

```python
# services/srv3_parser.py
def srv3_to_transcript_json(
    srv3_text: str,
    video_id: str,
    language: str = "ko",
) -> dict:
    """Parse yt-dlp srv3 to spec 010 transcript JSON.

    Skip rules (spike-confirmed):
      - <p a="1"> ASR rolling-display duplicate → skip
      - empty/whitespace <p> → skip
      - segment text = concat of all <s> child text in document order

    Returns:
        {"video_id": str, "language": str, "source": "ytdlp:auto",
         "segments": [{"start": float_sec, "end": float_sec, "text": str}, ...]}
    """

# services/ytdlp_adapter.py
CookiesBrowser = Literal["brave", "firefox", "chromium", "chrome", "edge", "opera", "vivaldi", "whale"]

def fetch_caption_via_ytdlp(
    video_url: str,
    output_dir: Path,
    cookies_browser: CookiesBrowser | None = "brave",          # spike 디폴트 확정
    cookies_path: Path | None = None,                           # secondary fallback
    sub_langs: tuple[str, ...] = ("ko", "ko-orig"),
    sleep_seconds: tuple[int, int] = (30, 60),
) -> Path | None:
    """Fetch ASR captions via yt-dlp, return path to srv3 file or None on failure.

    Caller responsible for srv3 → transcript JSON via `srv3_parser`.
    Returns None on: rate limit, no captions, auth fail, network error.
    Logs WARN with actionable English message ("Re-run 'tube-scout auth ...'" etc.).
    """

def fetch_audio_via_ytdlp(
    video_url: str,
    output_dir: Path,
    cookies_browser: CookiesBrowser | None = "brave",
    cookies_path: Path | None = None,
    sample_rate: int = 22050,
    audio_format: str = "mp3",
    sleep_seconds: tuple[int, int] = (30, 60),
) -> Path | None:
    """Download audio via yt-dlp, return path to extracted mp3 or None.

    postprocessor-args MUST use 'ffmpeg:' prefix (spike-confirmed:
    bare '-ar -ac' triggers WARN). Caller polices 'extract → fingerprint
    → unlink' lifecycle (Constitution V — 음원 영구 보관 금지).
    """

# services/audio_fingerprint.py
def extract_chromaprint_fingerprint(
    audio_path: Path,
    length_seconds: int = 0,                                    # 0 = full length
) -> tuple[bytes, float] | None:
    """Run fpcalc subprocess, return (fp_b64_bytes, duration_seconds) or None.

    NO pyacoustid — direct subprocess for robustness against
    audioread/ffmpeg dynamic-link breakage on NixOS. fpcalc binary
    self-links audio decoders (spike-confirmed).
    Returns None on: fpcalc failure, audio file missing/corrupt.
    """

def decode_fingerprint_to_array(fp_b64: bytes) -> "np.ndarray":
    """Decode chromaprint base64 to uint32 array (lazy import chromaprint module).

    Output shape: (n_frames,), dtype uint32. Frame rate ≈ 8.07 frames/sec
    (spike-measured). chromaprint module is shipped within pyacoustid
    PyPI package — no separate install needed.
    """

def hamming_distance_per_int(a: "np.ndarray", b: "np.ndarray") -> float:
    """Bit-level hamming distance averaged per uint32 (0..32 scale).

    Reference (spike-confirmed):
      - same audio: 0.0
      - different lectures: ~15-16 bits (~ 50% random baseline)
      - reuse candidate threshold: < 8 bits (< 25%) — spec Y will tune
    """

def best_alignment_hamming(
    a: "np.ndarray",
    b: "np.ndarray",
    window_frames: int = 400,
    step: int = 4,
) -> tuple[float, int]:
    """Search ±window_frames for min hamming distance.

    Returns (min_hamming_per_int, best_offset_frames).
    1 frame ≈ 0.124 sec (8.07 fps). Default ±400 frames ≈ ±50 sec,
    sufficient for intro/outro re-edit detection.
    """
```

**디폴트 결정 사유 (spike 직접 검증)**:
- `cookies_browser="brave"` — Brave keyring 디크립션 922-923 cookies 안정 추출
- `sleep_seconds=(30, 60)` — spike 5분 내 6 호출 / sleep 0 / 차단 0, 30s 안전 추정
- `sub_langs=("ko", "ko-orig")` — 두 트랙 다운로드 시 동일 ASR 결과 (재무손실), `ko` 우선 사용
- `--postprocessor-args` 필수 prefix 적용

### 4.3 Cross-Spec Boundaries (Constitution VII 사전 카탈로그)

| # | 상대 spec | 공유 자산 | 사전 측 보장 | 본 spec 신규 산출 / 가정 |
|---|---|---|---|---|
| B-X1-1 | spec 010 | `01_collect/transcripts/{vid}.json` 형식 | spec 010 transcript JSON 형식 권위 | yt-dlp srv3 → 동일 형식 변환 (srv3_parser.py) — boundary B-3 그대로 호환. spike에서 767 segments 무손실 변환 검증 |
| B-X1-2 | spec 011 | `02_analyze/content/content_reuse.db` v2 schema | spec 011 schema 권위 | `audio_fingerprint` 테이블 v3로 ALTER 추가 (idempotent migration) — spec 011 컬럼·테이블 변경 0. 예상 총량 ~5.5 GB (22ch × 4,000 영상 × 평균 25분, spike 측정 ~2 KB/min 기반) |
| B-X1-3 | spec Y (v0.6, 미래) | `audio_fingerprint` 테이블 | 본 spec이 production 형식 fix | spec Y가 본 테이블 read-only consume — 시그니처 동결. spike에서 V1↔V2 cross-hamming 47% 분리 능력 입증 → spec Y matching 가설 1차 통과 |
| B-X1-4 | spec 003 multichannel-admin | `--channel <alias>` flag | 별칭 → channel_id resolver 권위 | yt-dlp 명령에 별칭 받아 채널 video list 조회 |
| B-X1-5 | spec 009 runtime-auth-fix | OAuth 토큰 (`~/.config/tube-scout/tokens/`) | Data API 인증 권위 | yt-dlp 흐름은 OAuth 미사용. 단, `--source api` (spec 010 fallback) 시 spec 009 토큰 재사용 |
| B-X1-6 | agenix secret store | YouTube 쿠키 | Constitution VI | **spike 결과로 채택**: `--cookies-from-browser brave` 디폴트 (호스트 keyring 직접 접근, 환경변수 불필요). secondary `--cookies <path>` 만 0600 파일 + agenix 환경변수. 신규 secret 0건 (디폴트 경로) |
| B-X1-7 | 출력 디렉터리 컨벤션 | `projects/{job-id}/...` | Constitution V | `01_collect/transcripts/` 그대로 + 신규 `01_collect/audio_temp/` (처리 후 폐기 보장) |
| B-X1-8 | flake.nix devShell | NixOS 빌드 환경 | spike-confirmed 의존성 | **신규 의존성 5건 추가**: `yt-dlp`, `chromaprint` (libchromaprint.so), `ffmpeg`, `zlib` (numpy LD), `stdenv.cc.cc.lib` (libstdc++.so.6 LD). devShell `shellHook` 에 `LD_LIBRARY_PATH` 자동 export |

### 4.4 Constitution v1.1.0 7 원칙 사전 점검

| 원칙 | 영향 | 준수 |
|---|---|---|
| I (TDD) | RED → GREEN 의무 | ✅ 모든 어댑터 함수 RED-first |
| II (Fail-Fast) | yt-dlp 실패 → None + WARN + actionable 영문 | ✅ silent skip 0건, 모든 에러 영문 + "Run '...' first" 메시지 |
| III (Type Safety + SRP) | type hints + Google docstring | ✅ 모든 신규 함수 강제 |
| IV (CLI-First) | service-layer 우선 + thin CLI | ✅ adapter는 service-layer, CLI 한 줄 |
| V (Local-First) | 외부 DB 금지, 음원 폐기 | ✅ SQLite v3 + 음원은 처리 후 즉시 unlink |
| VI (agenix) | 쿠키는 agenix 또는 0600 로컬 | ✅ **spike 결과 - 신규 secret 0건** (cookies-from-browser brave 디폴트 채택, 호스트 keyring 직접 접근). secondary cookies.txt 사용 시만 0600 + agenix 환경변수 |
| VII (Cross-Spec) | B-X1-1~8 boundary 명시 | ✅ §4.3 카탈로그 (B-X1-8 flake.nix 추가) |

### 4.5 작업량 추산

| 항목 | 추정 | 실측/상태 |
|---|---|---|
| spike (탐색 검증) | 30~45분 | ✅ **45분 완료 (2026-05-09)**, 5/6 PASS + 1 PARTIAL |
| idea doc 보강 (spike 결과 반영) | 30분 | ✅ **완료 (2026-05-09)**, §3.4 / §4.2 / §4.3 / §5.1 / §6 / §7 갱신 |
| `/speckit.specify` → `/speckit.clarify` → `/speckit.plan` → `/speckit.tasks` | 1.5~2시간 | 다음 세션 |
| dev-squad 구현 (spec X1) | 5~7일 (spec 011 대비 약 1/4 규모) | 다음 세션 이후 |
| **총 spec X1 완료까지** | **약 1주** | spike 통과로 일정 확정 |

---

## §5. 운영 정책 (사전 합의)

### 5.1 영구 결정사항

| 항목 | 정책 |
|---|---|
| 자교 채널만 분석 | 외부 채널 yt-dlp 호출 영구 금지 (PS-A-12) |
| ToS 정당성 | 자교 자기 백업 (roadmap §5.2) |
| 음원 보관 | 추출 후 즉시 폐기 (지문만 영속) |
| Rate limit 디폴트 | **30~60초 random sleep** (spike: 5분 내 6 호출 / sleep 0 / 차단 0 — 30s 안전 추정. dev-squad가 50+ URL `@pytest.mark.slow` 로 production 검증) |
| 쿠키 관리 디폴트 | **`--cookies-from-browser brave`** (spike 검증, 호스트 keyring 직접). secondary: 0600 cookies.txt + agenix 환경변수. public repo commit 금지 |
| OAuth 토큰 영향 | 없음 (yt-dlp 경로는 cookies, OAuth 별개) |
| flake.nix devShell | spec X1 PR에서 `yt-dlp / chromaprint / ffmpeg / zlib / stdenv.cc.cc.lib` 5건 추가, `LD_LIBRARY_PATH` 자동 export (B-X1-8) |

### 5.2 운영 흐름 (spec X1 완료 후)

```bash
# scripts/weekly-backfill.sh — cron으로 매주
ALIASES=(nursing dental pharmacy ...)
for alias in "${ALIASES[@]}"; do
  tube-scout collect videos --channel "$alias"           # spec 003 — 메타만 (Data API 1u/영상)
  tube-scout collect transcripts --source ytdlp \         # spec X1 신규 — quota 0
    --channel "$alias" --sleep-min 30 --sleep-max 60
  tube-scout collect audio --channel "$alias"             # spec X1 신규 — 음원 추출 후 즉시 폐기 imminent
  tube-scout collect fingerprint --channel "$alias"       # spec X1 신규 — chromaprint 지문 영속 + 음원 unlink
done
```

위 4 명령으로 22채널 전체 백필. quota 사용 ≈ 4,000 unit (메타만, Data API 일일 한도 10K 안).

### 5.3 path C 가속 검토 (선택)

spike 통과 후 의사결정:
- **Path A (보수)**: spec X1 만 수행 → v0.4 자막 only 출시 (spec 011 + spec 014)
- **Path C (가속)**: spec X1 + spec Y (음향 지문 매칭) 동시 수행 → v0.4 자막+음향 출시 — 자막 부재 24영상 + 재녹음 false positive 동시 해결

Path C 추가 비용: 음원·지문 인프라는 spec X1으로 이미 들어와 있으므로 spec Y는 매칭 알고리즘만 추가 (~1주 dev-squad). v0.4 일정 +1~2주.

---

## §6. 위험 + 한계

### 6.1 사전 위험 (idea 작성 시점)

| 위험 | 완화 |
|---|---|
| YouTube anti-scraping 강화 | yt-dlp 매주 update — Nix flake에서 latest 추적 |
| cookies 만료 (3-6개월) | 운영자 쿠키 갱신 가이드 + cookies.txt fallback |
| 비공개 영상 정책 변경 | spec X1 fail-fast 시 actionable 메시지 + `--source api` 폴백 |
| 22채널 동시 다운로드 차단 | 채널별 시차 cron + 30~60초 sleep + IP reputation 학습 |
| 음원 추출 실패 (특정 인코딩) | per-video skip + audit CSV 기록 |
| chromaprint 짧은 영상 false negative | 30초 미만 영상 사전 제외 (Q-002 minimum_duration 재사용) |

### 6.2 spike에서 신규 발견된 위험 (2026-05-09)

| 위험 | 완화 |
|---|---|
| **NixOS LD_LIBRARY_PATH 의존 4건** (`libchromaprint`, `libz`, `libstdc++`, ffmpeg dynamic) | spec X1 `flake.nix` devShell `shellHook` 에 자동 export. CI(우분투)는 `apt install libchromaprint1 zlib1g` README에 명시. ImportError 시 actionable 영문 메시지로 안내 |
| **pyacoustid `fingerprint_file()` 부적합** — audioread 백엔드 의존, NixOS에서 `NoBackendError` 빈번 | `subprocess(fpcalc)` 단일 경로 채택 (Step 5 architecture 결정). pyacoustid 는 `chromaprint` 모듈 import 만 사용 — wheel 내 c-extension 자체는 가벼워 LD 문제 없음 |
| **`--postprocessor-args` 무명 PP WARN** — bare `-ar -ac` 시 WARN, 모든 PP에 args 전달 | 어댑터 모든 호출에 `ffmpeg:` prefix 강제. unit test로 검증 (`test_ytdlp_adapter.py::test_postprocessor_args_uses_ffmpeg_prefix`) |
| **rate limit boundary 미측정** — spike Step 6 PARTIAL (5-URL 시퀀스 미실행) | spec X1 dev-squad 단계에서 `tests/integration/test_ytdlp_rate_limit.py @pytest.mark.slow` 로 production 50+ URL 시퀀스 측정 (운영자 결정 시 실행) |
| **동일 강의자 baseline 미측정** — 한 채널 내 intro/outro 공통 반복이 false positive 유발 가능 | spec Y 진입 전 추가 spike 권장 (동일 채널 10영상 cross-matrix). 본 spec X1 scope 외 |
| **Brave keyring locked 상태** — agentized cron / headless 환경에서 디크립션 실패 가능 | spike 시점에서는 keyring unlocked 상태로 통과. cron 환경에서는 cookies.txt fallback 자동 전환 + agenix 환경변수로 path 주입 (B-X1-6) |

---

## §7. 다음 세션 시작 가이드 (spec specify 진입)

**spike 통과 (2026-05-09)** — 다음 세션은 spec specify 단계로 진입.

### 7.1 운영자 입력 (세션 첫 메시지 — 선택)

이미 idea 문서가 spike 결과로 갱신됨. 운영자 추가 입력 없이 바로 specify 가능. 단, 선택적으로 다음을 미리 결정해두면 `/speckit.clarify` 단축:

- spec X1 scope 추가/제외 항목 (예: 비디오 메타 fetch 통합 여부)
- path C 가속 (spec X1 + spec Y v0.4 동시 출시) 결정 — Y/N
- `tests/integration/test_ytdlp_rate_limit.py @pytest.mark.slow` 의 50-URL 시퀀스 실행 여부

### 7.2 메인 세션 워크플로 (spec specify → tasks → dev-squad)

1. (이미 완료) idea 문서 §4.2 시그니처 / §6 위험 / §5.1 정책에 spike 결과 반영
2. `/speckit.specify idea/idea-2026-05-09-spec-X1-ytdlp-adapter.md` 진입 → `specs/X1-ytdlp-adapter/spec.md` 생성
3. `/speckit.clarify` (선택) → 모호한 요구사항 해소
4. `/speckit.plan` → 구현 계획 + Constitution 7 원칙 점검
5. `/speckit.tasks` → tasks.md 생성 (TDD RED-GREEN-REFACTOR)
6. dev-squad 호출 → developer + pair-programmer + auditor + adversary 동시 spawn (`feedback_devsquad_full_team` 정책)
7. dev-squad 완료 → master 머지 → v0.4 출시 또는 spec Y 진입 (path C 결정)

### 7.3 spec specify 시 우선 반영할 입력

다음 항목은 `_workspace/spike/ytdlp_feasibility.md` 의 직접 인용:

| spec 항목 | spike 출처 |
|---|---|
| FR (Functional Requirements) — caption fetch | Step 1, 2 결과 + srv3 파싱 규칙 |
| FR — audio extraction | Step 3 결과 (postprocessor-args ffmpeg: prefix) |
| FR — fingerprint extraction | Step 4 + Step 5 architecture 결정 (subprocess fpcalc) |
| FR — similarity API | Step 5 hamming/best_alignment 시그니처 |
| NFR (Non-Functional) — rate limit | Step 6 PARTIAL → `@pytest.mark.slow` 로 위임 |
| NFR — performance | Step 3 wall-clock (~0.5초/영상분), Step 4 fpcalc <1초 |
| Constraint — NixOS LD | Step 5 LD_LIBRARY_PATH 4 lib |
| Constraint — Brave keyring unlocked | Step 1 922 cookies 디크립션 |
| Schema — `audio_fingerprint` 테이블 | Step 4 b64 BLOB + duration + extracted_at |

### 7.4 path C 가속 검토 시 spec Y 추가 spike 항목 (선택)

spec Y (음향 매칭) 진입 전 권장:
- 동일 강의자 한 채널 10 영상 cross-matrix → intro/outro 공통 반복 baseline 측정
- 같은 슬라이드 다른 음성 (재녹음) hamming 분포 측정 → false positive 임계 calibrate
- 두 spike는 spec X1 완료 후 데이터 (production fingerprint) 활용 — 별도 영상 다운로드 불필요

---

## §8. 참조 메모리

- `project_dev_status.md` — 전체 개발 현황 (spec 011 35 commits 완료, master 미머지)
- `project_data_acquisition_strategy.md` — yt-dlp 운영 모델, v0.4~v1.0 로드맵 ★ 본 spec의 핵심 입력
- `project_scope_decisions_20260506.md` — OCR·화자분리 영구 제외
- `project_public_repo_transition.md` — 익명화 매핑
- `feedback_secrets_architecture.md` — agenix 중앙 저장소 + 환경변수 참조 (B-X1-6 적용)
- `feedback_runtime_integration_gaps.md` — D-13~D-17 boundary 결함 학습 (통합 결정 근거)
- `feedback_cross_spec_consistency.md` — D-1~D-12 (spec 분리 비용 학습)
- `feedback_version_policy.md` — idea 번호 ≠ 제품 버전, GPG 자동화 commit bypass 허용

## §9. 참조 문서

- `idea/idea-2026-05-09-roadmap.md` §3 (자막 한계 4가지 + 보완 신호 매트릭스)
- `idea/idea-2026-05-09-roadmap.md` §5 (데이터 acquisition 전략 + yt-dlp 운영 모델)
- `idea/idea-2026-05-09-roadmap.md` §7 (PS-A-2 ASR 노이즈, PS-A-6 무자막 강의 — 본 spec 해결 대상)
- `specs/011-reuse-fullstack-subtitle/spec.md` (spec 011 boundary B-3 — 본 spec 산출물 spec 011이 소비)
- `specs/010-prefer-captions-resume/spec.md` (transcript JSON 형식 — boundary B-X1-1)
