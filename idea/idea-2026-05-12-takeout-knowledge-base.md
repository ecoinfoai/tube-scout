# Tube Scout idea (2026-05-12) — Takeout 기반 강의 영상 분석 + Knowledge Base 구축

**작성일**: 2026-05-12
**상태**: Draft (spec 016 입력 문서)
**선행 결정**:
- `memory/project_takeout_pivot_20260512.md` — yt-dlp 영구 폐기, Google Takeout export 전환 (NON-NEGOTIABLE)
- `memory/feedback_external_comms_no_takeout.md` — 외부 커뮤니케이션(YouTube/Google 등)에는 Takeout 사실 비공개

---

## 1. 배경

2026-05-12에 데이터 수집 전략을 yt-dlp에서 Google Takeout export로 전환했다. spec 012(yt-dlp 어댑터)는 master에 머지된 상태로 남아 있으나 deprecated 처리되며, spec 013/014/X/Y는 영구 폐기되었다. 이 결정은 운영자 명시 권위 결정이고 본 idea의 모든 설계는 이 결정 위에서 출발한다.

idea4(강의 영상 재사용 탐지)의 자막 5지표(I-1 ~ I-5)와 M-default 매칭은 spec 007로 이미 master에 들어가 있다. 시간축 3지표(I-6 / I-7 / I-8)와 M-nC2 매칭 모드, 4계층 오탐 방어, 재활용 4패턴 분류는 spec 011 P1 작업으로 미완 상태로 남아 있다. 본 idea는 Takeout pivot 이후의 새로운 데이터 acquisition 모델 위에서 spec 011 미완 부분을 완성하고, 거기에 음원 지문 + faster-whisper STT + 교수 단위 통합 보고서를 결합한다.

이 idea의 산출물은 spec 016 한 건이 될 예정이다. spec 016 명칭은 추후 결정한다(후보: `016-takeout-knowledge-base`).

---

## 2. 핵심 목적

이 idea의 작업 결과로 운영자가 얻는 가치는 두 가지다.

**(1) 강의 영상 콘텐츠 재사용의 종합 판정.**
한 교수 단위(예: 정광석 교수의 200여 개 영상)의 영상 풀 전체에 대해, 두 개씩 짝지어 비교한 결과를 한 부의 PDF 보고서로 묶는다. 본문에는 의심도 상위 항목만 요약하고, 개별 1:1 비교 상세는 임계를 넘은 쌍만 부록으로 분리한다. 교무 검토자는 이 한 부의 보고서만으로 "이 교수의 어떤 영상 쌍이 재활용 의심인지" 1차 판단을 내릴 수 있다.

**(2) 선별 영상의 자막 텍스트 추출 — knowledge base 구축의 원천 자료.**
운영자가 특정 영상(자기 강의나 우수 강의)의 자막을 깨끗한 텍스트 파일로 받아, 외부 knowledge base 도구(검색 인덱스, RAG, LLM 미세조정 등)의 입력으로 사용한다. KB export 자체는 단순 CLI 한 개로 끝나며, 입력 자막은 본 idea의 수집·정규화·ASR 파이프라인 산출물(공개 영상은 API caption, 비공개 영상은 ASR)을 그대로 재사용한다.

---

## 3. 설계 원칙

idea4의 C4R 원칙(Comfortableness / Continuity / Conciseness / Consistency / Robustness)을 그대로 계승하고 다음 세 가지를 추가한다.

- **로컬 우선 (acquisition과 분석의 경계 명시)**: 모든 **분석·STT 처리**는 로컬 머신에서 실행한다. 외부 클라우드 분석/STT API(OpenAI Whisper API, Google Cloud STT, Naver Clova, Azure 등)는 도입하지 않는다. 단 **소유 채널의 자가 데이터 acquisition 경로**(YouTube Data API의 `captions.list` / `captions.download`)는 선택적으로 허용한다. 이는 데이터 소유자가 자신의 콘텐츠를 받아오는 행위로, 외부 분석 위탁과는 성격이 다르다.
- **이중 GPU 환경 지원**: PoC는 이 머신(RTX 3060 Laptop, VRAM 6 GB), 운영은 별도 GPU 서버(NVIDIA A6000 ×2, VRAM 48 GB ×2). 동일 CLI가 양쪽에서 모두 동작하도록 모델 크기·정밀도·디바이스 인덱스를 옵션으로 노출한다.
- **누적 가능 ingestion**: Takeout export는 분할 압축으로 제공된다(`3-001`, `3-002`, `3-003`, …). 같은 영상이 여러 part에 걸쳐 있을 수 있고, 같은 part를 재ingestion할 수도 있어야 한다. 모든 ingestion 단계는 멱등(idempotent)이어야 한다.

---

## 4. 전제 조건

- spec 007(자막 5지표 + M-default) master 머지 완료, 권위 코드.
- spec 011 부분 머지 — 시간축 지표 + M-nC2 + 4계층 + 4패턴은 본 idea에서 완성.
- spec 012(yt-dlp 어댑터) deprecated. 코드 제거 시점은 본 idea의 마지막 단계에서 결정.
- Takeout export 1차분(`data/takeout-20260511T130817Z-3-001/`)이 디스크에 압축 해제되어 있음. 9개 mp4 + 39개 메타데이터 CSV + 채널·댓글·재생목록·구독·시청기록 CSV.
- chromaprint(`fpcalc 1.6.0`)와 ffmpeg는 `flake.nix` devShell에 이미 설치되어 있음.
- 검증 완료(2026-05-12): `services/audio_fingerprint.py:62 extract_chromaprint_fingerprint(mp4_path)`는 takeout mp4를 직접 입력받아 정상 동작한다. 9개 영상 일괄 실행 결과 모두 메타데이터 길이와 ±1초 이내 일치, 추출 시간 0.1~4.9초/영상.

---

## 5. 입력 데이터 — Google Takeout export 구조

압축 해제 결과 `Takeout/YouTube 및 YouTube Music/` 아래 7개 카테고리가 존재한다.

| 디렉터리 | 내용 | 사용처 |
|---|---|---|
| `동영상/` | mp4 파일 (1차 export에 9개, 총 9.9 GB) | 음원 지문 + ASR 입력 |
| `동영상 메타데이터/` | CSV 39개 (3종 × 13파일 분할) — video_id · 길이 · 언어 · 채널 ID · 제목 · 공개상태 · 생성 타임스탬프 · 위경도 · 텍스트 세그먼트 | `videos_meta.json` 생성, mp4 ↔ video_id 매핑 |
| `채널/` | `채널.csv` 외 5개 | `channel_meta.json` 생성 |
| `댓글/` | `댓글.csv` | 자교 채널은 분석 제외(메모리 정책 `project_no_comments.md`) |
| `재생목록/` | `재생목록.csv` | 본 idea scope OUT |
| `구독정보/` | `구독정보.csv` | 본 idea scope OUT |
| `시청 기록/` | `시청 기록.html`, `검색 기록.html` | 본 idea scope OUT (개인정보 영역) |

메타데이터 CSV는 채널 전체 영상 정보(현재 1차 part 기준 2,555개)를 담지만, 실제 mp4 파일은 한 export part에 일부만 들어 있다. 채널 전체 영상에 접근하려면 분할 export를 모두 받아 통합해야 한다.

**자막은 Takeout export 카테고리에 포함되지 않는다.** 자막이 필요한 영상은 (a) 공개 영상이면 YouTube Data API caption 엔드포인트, (b) 비공개 영상이면 faster-whisper로 ASR을 돌려 새로 생성한다.

---

## 6. 시스템 아키텍처

```
[Takeout export 디렉터리]
        │
        ▼
[Takeout ingestion 어댑터]                        ← 신규 (spec 016)
   ├─ 메타데이터 CSV → channel_meta.json + videos_meta.json
   ├─ mp4 파일명 ↔ video_id 매핑 (제목 정규화 매칭)
   └─ processing_status 테이블 업데이트
        │
        │
        ▼
[오디오 추출 전처리]                              ← 신규 (이중 디코딩 방지)
   mp4 → ffmpeg → 16 kHz / mono WAV
   분리 CLI: 캐시 누적 / 통합 CLI: 영상별 즉시 삭제
        │
        ├──────────────────────┬──────────────────┐
        ▼                      ▼                  ▼
[음원 지문 추출]          [ASR 자막 생성]    [공개 영상 자막 다운로드]
chromaprint            faster-whisper      YouTube Data API
fpcalc 1.6.0           CTranslate2         captions.download
   │                      │                  │
   ▼                      ▼                  ▼
audio_fingerprint      transcripts/         transcripts/
(SQLite v3)            <video_id>.json      <video_id>.json
                       (spec 011 호환)      (spec 011 호환)
        │                      │
        └──────────────────────┘
                   │
                   ▼
[Text Normalizer]                              ← 신규 (이기종 자막 정규화)
   구두점·특수기호 제거, 공백 정규화, 공통 토큰화
   YouTube auto-caption ↔ Whisper 출력 형태 차이 흡수
                   │
                   ▼
[분석 단계 — spec 011 파이프라인]
   ├─ 자막 5지표 I-1 ~ I-5            (spec 007 구현됨)
   ├─ 자막 시간축 3지표 I-6 ~ I-8     ← 본 idea 완성
   ├─ M-nC2 매칭 모드                 ← 본 idea 완성
   ├─ 4계층 오탐 방어 (A/B/C/D)       ← 본 idea 완성
   ├─ 재활용 4패턴 분류                ← 본 idea 완성
   └─ 음원 지문 nC2 비교               ← 본 idea 신규
                   │
                   ▼
[보고서 (PDF + HTML)]                ← spec 006 인프라 확장
   ├─ 본문: 교수 단위 요약 + 의심 top-K + 분포 차트
   └─ 부록: 임계 이상 의심 쌍 1:1 상세

[knowledge base export]              ← 독립 단순 CLI
transcripts/<video_id>.json → cleaned text file
```

---

## 7. 컴포넌트별 상세

### 7.1 Takeout ingestion 어댑터

**역할**: Takeout 디렉터리를 입력으로 받아 spec 007 이후의 분석 파이프라인이 그대로 받을 수 있는 표준 데이터 구조(`channel_meta.json`, `videos_meta.json`, `processing_status` 테이블)를 만든다.

**핵심 작업**:

1. **메타데이터 CSV 통합 파싱.** 13개 분할 CSV(`동영상.csv`, `동영상(1).csv`, …, `동영상(12).csv`)를 합쳐 video_id 기준 deduplicate. 채널 ID는 `채널.csv`에서 추출. 영상 길이는 밀리초 단위에서 초 단위로 변환.

   본 idea가 **사용하지 않는** CSV 종류는 다음과 같다. ingestion 어댑터는 이들을 명시적으로 무시한다:
   - `동영상 녹화(*).csv` — 위경도 정보. scope OUT.
   - `동영상 텍스트(*).csv` — 제목/설명의 텍스트 세그먼트 메타데이터(자막이 아님). scope OUT.
   - `댓글.csv` — 자교 채널 댓글 무시 정책(`project_no_comments`).
   - `재생목록.csv`, `구독정보.csv`, `시청 기록/*.html`, `검색 기록.html` — scope OUT.

2. **mp4 파일명 ↔ video_id 매핑 — Evidence Score 기반 가중치 합산.** Takeout mp4 파일명은 영상 제목 그대로이며 video_id가 들어 있지 않다. 제목 문자열 매칭만으로는 OS 파일명 길이 제한(255자) 절단, YouTube/Takeout 사이의 미세한 특수문자 처리 차이, 동일 제목의 재업로드 케이스 때문에 실패가 잦다. 그렇다고 단일 결정타(mtime 등)에 의존하면 압축 해제·복사·외장 디스크 동기화 과정에서 신호가 손상될 수 있다. 따라서 여러 신호를 가중치 합산형 evidence score로 묶어 후보 video_id를 순위화한다.

   각 (mp4 파일, 후보 video_id) 쌍에 대해 다음 신호를 평가한다:

   | 신호 | 가중치 | 비고 |
   |---|---|---|
   | 파일명 ↔ 제목 정확 일치 | +40 | 가장 강한 신호 |
   | 파일명 ↔ 제목 정규화 일치(공백·기호 제거 후) | +30 | 정확 일치 실패 시만 |
   | `ffprobe` duration ↔ 메타 `근사치 길이`(±1초) | +25 | 독립적 물리량 |
   | 파일 크기 ↔ 영상 길이의 합리적 비율 | +5 | 단순 sanity check |
   | 파일 mtime ↔ 메타 `동영상 생성 타임스탬프`(±1일) | +5 | **보조 신호로만** — 압축 해제·복사로 쉽게 손상 가능 |

   각 mp4에 대해 가장 높은 점수의 video_id를 선택. 임계 정책:
   - `score ≥ 65`: **high-confidence** 자동 매핑.
   - `40 ≤ score < 65`: **medium-confidence** 자동 매핑 + 검토 큐 별도 표기.
   - `score < 40`: **unmapped**(어느 후보도 충분한 evidence 없음) — `_ambiguous_mappings.csv`로.
   - 동점 후보가 둘 이상이면 **ambiguous** — 동 CSV로.

   가중치와 임계값은 Phase 1 실측 후 튜닝한다(현재 수치는 출발점 — `[VERIFY]`).

   **운영자 검토 큐 위치**: `01_collect/_ambiguous_mappings.csv`. 컬럼: `mp4_filename`, `candidate_video_ids`(쉼표 구분), `scores`(쉼표 구분), `signals_breakdown`(JSON), `reason`. 운영자가 한 행에 한 video_id로 정리한 뒤 ingestion 재실행 시 결정이 반영된다(멱등). admin web UI 통합은 본 idea scope OUT.

   **수동 override CSV (1급 source)**: `01_collect/_manual_mappings.csv`가 존재하면 evidence score 계산을 건너뛰고 그 매핑을 그대로 따른다. 운영자가 미리 알고 있는 케이스는 이 파일에 적어 두면 자동 매핑 단계를 우회한다.

3. **`processing_status` 테이블 등록.** 각 video_id에 대해 row 추가. 멱등(`INSERT OR IGNORE`).

   현재 코드(`src/tube_scout/models/content.py:21`)의 `VALID_PROCESSING_STATUSES`는 `{pending, collecting, collected, fingerprinted, compared, failed, no_caption}`이고 `VALID_CAPTION_SOURCES`는 `{transcript_api, captions_api, whisper}`이다. Takeout 경로를 깨끗하게 수용하려면 enum과 컬럼 확장이 필요하므로 **v4 마이그레이션에서 다음을 추가**한다(§8 DDL 참조):

   - `match_confidence` (TEXT) — `'high' | 'medium' | 'ambiguous'`.
   - `caption_source_detail` (TEXT) — `'asr:faster-whisper:large-v3:int8_float16'` 같은 정밀 식별자(재현성). 기존 `caption_source` enum은 그대로 유지(`transcript_api | captions_api | whisper`)하고 detail만 분리.
   - `VALID_PROCESSING_STATUSES`에 `asr_in_progress`, `asr_failed` 두 값 추가. Python 측 frozenset 갱신과 SQLite CHECK constraint 동시 반영.

   Takeout ingestion 직후 row 상태: `status='collected'`, `caption_source=NULL`(추후 ASR 또는 API caption 단계에서 갱신), `match_confidence`는 §7.1 매핑 결과 그대로.

**CLI**:
```
tube-scout collect takeout
    --takeout-dir <path>
    --channel <alias>
    [--dry-run]
```

**멱등성**: 같은 takeout 디렉터리를 두 번 실행해도 부작용 없음. 다른 part(`3-002`, `3-003`, …)를 추가로 실행하면 새 video_id만 누적.

**제외 처리**: 댓글 CSV는 자교 채널 정책에 따라 무시. 시청기록/검색기록 HTML은 본 idea scope OUT.

---

### 7.2 오디오 추출 전처리 — 지문·STT 공통 입력 (신규)

**역할**: mp4 컨테이너에서 오디오 트랙만 분리하여 가벼운 단일 파일로 만들고, 음원 지문 추출과 STT가 동일한 오디오 파일을 입력으로 받도록 한다. 두 단계가 각자 mp4를 디코딩하는 이중 디코딩(double-decoding) 낭비를 제거한다.

**작업 내용**:

```
ffmpeg -i <input.mp4> -vn -ac 1 -ar 16000 -c:a pcm_s16le <tmp>/<video_id>.wav
```

- 비디오 스트림 제거(`-vn`), 모노 다운믹스(`-ac 1`), 16 kHz 리샘플(`-ar 16000`), 16-bit PCM WAV로 출력.
- 16 kHz / mono는 faster-whisper 권장 입력 사양.
- 9개 takeout mp4(총 9.9 GB)에서 추출 시 WAV 합산 크기는 Phase 1 실측 항목(추정 단언 없음 — `[VERIFY]`).

**Sample rate 결정과 음원 지문 일관성 — `fingerprint_input_policy` 설정값**:

`services/audio_fingerprint.py:62 extract_chromaprint_fingerprint`는 fpcalc CLI를 호출한다. 입력 오디오의 sample rate에 따라 chromaprint 출력이 동일한지 여부는 본 idea 시점에 **검증되지 않았다(`[VERIFY]`)**. STT 입력은 16 kHz가 권장 사양으로 분명하지만, 음원 지문 입력에 대해 같은 결정을 내릴 근거는 아직 없다. 따라서 다음과 같이 분리해 설정값으로 둔다.

```
fingerprint_input_policy ∈ {original_mp4, wav_16k, wav_22k}
```

- `original_mp4`: mp4 직접 입력. 현재 master 9개 지문이 이 방식으로 산출됨.
- `wav_16k`: §7.2 추출 결과 그대로 사용(STT와 입력 공유).
- `wav_22k`: chromaprint canonical sample rate로 별도 추출.

**Phase 1 실측 항목**:
- 동일 영상을 세 방식으로 각각 지문 산출 후 hamming distance 측정.
- 결과가 noise 수준이면 `wav_16k` 채택(STT와 입력 통합 가능).
- 차이가 크면 `original_mp4` 또는 `wav_22k` 채택(STT와 입력 분리, 디코딩 두 번 발생 — 이 경우 §7.2 추출 단계는 STT 전용으로만 사용).

Phase 1 종료 시점까지 기본값은 **확정하지 않는다**. CLI 옵션은 받지만 기본값은 명시적으로 비워 두고, 실측 결과로 spec 016 spec.md에서 확정한다.

**저장 정책 (라이프사이클)**:
- 임시 디렉터리(예: `/tmp/tube-scout-audio/`) 또는 `--audio-cache-dir`로 지정한 경로에 보관.
- 분리 CLI 실행 시 wav는 캐시에 누적된다(다음 단계에서 입력으로 재사용). 통합 파이프라인 실행 시 영상별 처리 후 즉시 삭제.
- `--keep-audio` 플래그로 분리/통합 양쪽에서 강제 보존 가능.
- 동일 video_id의 wav가 이미 존재하면 재사용(멱등).

**CLI (분리 모드)**:
```
tube-scout collect audio-extract
    --channel <alias>
    [--video-ids <comma-separated>] [--all-takeout]
    [--audio-cache-dir <path>]
    [--keep-audio]
    [--sample-rate 16000] [--codec pcm_s16le | flac]
```

**통합 파이프라인 옵션 (영상별 라이프사이클 묶음)**:

분리 CLI를 학과 전체(예: 2,555개 영상)에 적용하면 WAV 캐시 누적이 디스크에 부담을 준다. 그래서 영상 1개 단위로 [WAV 추출 → 지문 산출 → STT 실행 → WAV 삭제] 루프를 도는 통합 명령을 별도로 제공한다:

```
tube-scout collect process-audio
    --channel <alias>
    [--video-ids ...] [--all-takeout]
    --preset poc-laptop | prod-a6000 | prod-a6000-pool | cpu-fallback
    [--skip-fingerprint] [--skip-asr]
    [--keep-audio]
```

이 명령은 §7.3 음원 지문 + §7.4 STT 단계를 내부적으로 영상 단위로 묶어 실행하므로, 캐시 누적 없이 끝난다. 운영자가 단계별 실행이 필요할 때만 분리 CLI를 사용한다.

**Phase 1 검증 지표**: 9개 takeout 영상에서 wav 추출 성공률 + 추출 시간 + 결과 파일 크기 분포. wav 추출이 mp4 직접 사용 대비 음원 지문·STT 처리시간을 단축하는지 실측한다(가능성에 의존하지 않고 숫자로 확인).

---

### 7.3 음원 지문 추출 (로컬 오디오 입력 경로)

**역할**: 로컬 오디오를 입력으로 받아 chromaprint 음원 지문을 SQLite v3 `audio_fingerprint` 테이블에 저장한다.

**입력 — `fingerprint_input_policy`에 따라 분기**: §7.2에서 도입한 설정값 `fingerprint_input_policy ∈ {original_mp4, wav_16k, wav_22k}`에 따라 원본 mp4 또는 §7.2에서 추출된 wav를 입력으로 받는다. 기본값은 Phase 1 실측 후 spec 016 spec.md에서 확정한다. 셋 모두 `extract_chromaprint_fingerprint(audio_path)` 함수 한 개로 처리 가능하며(fpcalc 내부 ffmpeg가 양쪽 디코드 모두 처리), 디코딩 비용 통합 여부는 정책에 종속된다.

**기존 코드 재사용**:
- `services/audio_fingerprint.py:62 extract_chromaprint_fingerprint(audio_path, length_seconds=0)` — mp4·wav 입력 양쪽 가능.
- `storage/content_db.py:790 insert_audio_fingerprint(...)` — DB persist.
- `storage/content_db.py:764 migrate_to_v3()` — `audio_fingerprint` 테이블 생성.

**신규 작업**: CLI 진입점만 추가. 기존 `dispatch_audio_fingerprint`(`cli/collect.py:242`)는 yt-dlp 다운로드 경로에 묶여 있으므로 사용하지 않는다. 로컬 입력(mp4 또는 wav)을 받는 새 진입점을 만든다.

**CLI**:
```
tube-scout collect fingerprint
    --source local
    --channel <alias>
    [--video-ids <comma-separated>]
    [--all-takeout]
    [--input-kind mp4 | wav_16k | wav_22k]   # fingerprint_input_policy 명시적 지정
    [--force]
```

**실측 결과 (2026-05-12, 9개 takeout 영상)**:

| 영상 | 크기 | 길이 | 지문 크기 | 추출 시간 |
|---|---|---|---|---|
| 5-1.임경민 (가장 짧음) | 28 MB | 105 s | 1.9 KB | 0.1 s |
| 9-2.리차드방 (가장 큼) | 6.3 GB | 1309 s | 42.9 KB | 4.9 s |
| 19-2.허제은 (가장 김) | 1.9 GB | 2948 s | 98.9 KB | 3.3 s |

전 영상 메타데이터 길이와 ±1초 이내 일치. 9개 합산 지문 462 KB → 채널 전체 2,555개 영상으로 외삽 시 약 130 MB. SQLite BLOB 컬럼 용량으로 충분히 감당 가능.

---

### 7.4 STT (faster-whisper)

**역할**: 자막이 없는 영상(주로 비공개)에서 음성을 인식하여 spec 011이 받는 표준 자막 JSON 포맷으로 출력한다.

**입력**: §7.2에서 추출된 16 kHz mono wav. mp4를 직접 받지 않는다(이중 디코딩 방지).

**기술 선택**: faster-whisper(CTranslate2 백엔드). OpenAI Whisper 본가 대비 동일 정확도에서 4~5배 빠르고, int8 양자화 지원으로 VRAM 사용량이 절반 이하. transformers/torch 의존성 없이 단일 패키지로 추가.

**모델·정밀도 옵션 (CLI 노출)**:

| CLI 옵션 | 값 | 비고 |
|---|---|---|
| `--model` | `tiny` / `base` / `small` / `medium` / `large-v3` | 한국어는 `large-v3` 권장 |
| `--compute-type` | `float32` / `float16` / `int8_float16` / `int8` | A6000은 `float16`, 이 머신은 `int8_float16` |
| `--device` | `cuda:0` / `cuda:1` / `cpu` | A6000 ×2 동시 활용 시 두 프로세스로 분할 |
| `--language` | `ko` / `en` / `auto` | 강의 채널은 `ko` 고정 |
| `--beam-size` | int (기본 5) | 정확도-속도 트레이드오프 |

**Whisper 환각(hallucination) 방어 옵션 — 기본 강제**:

강의 영상은 판서·학생 응답 대기 등으로 무음 구간이 길다. 이때 Whisper 계열 모델은 "시청해주셔서 감사합니다", "구독과 좋아요 부탁드립니다" 같은 학습 데이터 잔재를 무한 반복 생성하는 고질적 환각 증세가 있다. 본 idea에서는 다음 세 가지 방어를 기본값으로 강제한다.

| CLI 옵션 | 기본값 | 의미 |
|---|---|---|
| `--vad-filter` | `True` (강제) | Voice Activity Detection으로 무음 구간 사전 제거 |
| `--condition-on-previous-text` | `False` | 앞 세그먼트의 환각 텍스트가 다음 추론을 오염시키는 연쇄 방지 |
| `--compression-ratio-threshold` | `2.4` | 비정상적 텍스트 반복은 압축률이 급등 — 임계 초과 세그먼트 drop |
| `--no-speech-threshold` | `0.6` | 무음 확률이 임계 이상이면 빈 출력 |

추가로 출력 자막 JSON 후처리에서 다음 품질 플래그를 검출하여 `quality_results` 테이블에 신규 컬럼 `asr_quality_flags`(JSON 텍스트)로 기록한다. ASR 품질 이슈는 단일 boolean으로 표현하기에 종류가 많아 계속 늘어날 가능성이 크므로, 단일 컬럼 대신 확장 가능한 JSON 구조를 사용한다.

```json
{
  "hallucination_repeat": true,        // 동일 텍스트가 연속 3회 이상 반복
  "vad_over_truncated": false,         // VAD가 발화 구간을 과도하게 잘랐는지
  "language_mismatch": false,          // language=ko 강제했는데 영어 출력 비중 높음
  "short_segments_excess": false,      // 0.5초 미만 세그먼트 비중이 임계 초과
  "silence_hallucination": false,      // 무음 구간에 학습 잔재 텍스트 출력
  "compression_ratio_violations": 2    // compression_ratio_threshold 초과 세그먼트 수
}
```

플래그 종류는 운영 데이터로 추가·삭제될 수 있다. 데이터 모델 측에서는 JSON 스키마 검증(jsonschema) 또는 Pydantic 모델로 강제하되, DB 스키마는 단일 TEXT 컬럼으로 유지(future-proof).

**환경별 프리셋** (단축 옵션):
- `--preset poc-laptop`: `large-v3` + `int8_float16` + `cuda:0` (이 머신용)
- `--preset prod-a6000`: `large-v3` + `float16` + `cuda:0` (운영 GPU 서버 단일 GPU)
- `--preset prod-a6000-pool`: 두 프로세스 워커 풀, cuda:0 / cuda:1 각각 전담(§12 4번 권장 방향)
- `--preset cpu-fallback`: `medium` + `int8` + `cpu` (GPU 없는 환경)

**출력 포맷**: spec 011이 받는 자막 JSON과 동일 스키마. 세그먼트마다 `start`, `end`, `text` 필드. 파일 위치 `01_collect/transcripts/<video_id>.json`. 두 컬럼에 나눠 기록한다 — `processing_status.caption_source='whisper'`(기존 enum 값 그대로 사용), `processing_status.caption_source_detail='asr:faster-whisper:large-v3:int8_float16'`(v4 마이그레이션 신규 컬럼). 이는 §7.1에서 명시한 enum 호환 정책을 따른다.

**CLI**:
```
tube-scout collect transcripts
    --source asr
    --channel <alias>
    [--video-ids <comma-separated>]
    --preset poc-laptop | prod-a6000 | prod-a6000-pool | cpu-fallback
    [--model ...] [--compute-type ...] [--device ...]
    [--vad-filter / --no-vad-filter]  # 기본 on, 비활성화 시 명시적 opt-out
    [--cleanup-audio]                 # STT 완료 후 §7.2 캐시의 해당 video_id wav 삭제
    [--auto-normalize / --no-auto-normalize]  # 기본 on, 완료 후 §7.5 Text Normalizer 자동 호출
```

**`prod-a6000-pool` 워커 풀 정책 (운영 환경 전용)**:

한 영상씩 단일 GPU에 dispatch하면 A6000 한 장이 idle인 시간이 길어진다. `prod-a6000-pool` 프리셋은 두 개의 Python 프로세스를 띄워 cuda:0과 cuda:1을 각각 전담시키고, 둘이 공유하는 video_id 작업 큐에서 독립적으로 작업을 소비하는 구조를 사용한다.

- 작업 큐는 SQLite의 `processing_status` 테이블을 그대로 사용한다(별도 큐 인프라 도입 없음). 워커는 `status='collected'` AND `caption_source IS NULL`인 row를 트랜잭션 안에서 `status='asr_in_progress'`로 claim한 뒤 처리한다.
  - `asr_in_progress`, `asr_failed`는 §7.1에 명시한 v4 마이그레이션에서 `VALID_PROCESSING_STATUSES`에 추가되는 값(현재 enum에는 없음).
- 영상 1개의 처리는 [WAV 추출 → STT → JSON 저장 → caption_source 갱신]이 한 트랜잭션 단위.
- 한 워커가 처리 중에 실패하면 row를 `status='asr_failed'`로 표시하고 다음 작업으로 진행. 운영자가 재시도하려면 `--retry-failed`로 다시 실행.
- 모델 단위 sharding(예: encoder는 cuda:0, decoder는 cuda:1)은 inter-GPU 통신 오버헤드 때문에 채택하지 않는다.

세부 동작은 §12 항목 4에 미해결 사항으로 남아 있으며 spec 016 작성 시 spec.md에서 확정한다.

**PoC 영상**: `5-1.임경민_간호연구세미나_8주차_1차시` (video_id `sUJbkkYzNGc`, 105초). 가장 짧으므로 RTX 3060 6 GB에서 검증 부담이 가장 작다.

---

### 7.5 자막 비교 메트릭 (8지표 + 매칭 모드 + 4계층 + 4패턴)

본 idea에서 spec 011의 미완 부분을 완성한다. 자세한 설계는 spec 011 `spec.md` / `data-model.md` / `research.md`에 이미 정리되어 있으므로 여기서는 본 idea의 관점에서 요점만 정리한다.

**Text Normalizer 사전 단계 — 이기종 자막 정규화 (신규 강제)**

본 idea의 자막은 두 가지 출처를 가진다: faster-whisper ASR 출력(VAD 통과, 구두점 포함, 정제된 문장)과 YouTube Data API caption 다운로드(분절 단위 다름, 구두점 누락 빈번). 이 두 형태를 그대로 비교하면 실제 동일 내용임에도 점수가 낮게 나오는 false negative가 발생한다. 따라서 **모든 비교 지표 계산 전에 공통 Text Normalizer를 강제 통과**시킨다.

정규화 규칙:
- 구두점 및 특수기호 제거(`.`, `,`, `?`, `!`, `~`, `…`, 쌍따옴표 등).
- 연속 공백 단일화, 줄바꿈 제거.
- 한글 자모 단독 표기 정규화(NFC).
- 영문 대소문자 통일(소문자).
- ASR 잡음 패턴 제거(`[음악]`, `[박수]`, `(...)` 등 메타 표기).
- 출처 식별자(`source_type` ∈ {`asr`, `api`, `manual`})를 비교 쌍 메타데이터에 기록하여, 보고서에서 "이기종 비교"임을 명시.

정규화 결과는 원본 자막 JSON과 별도로 `01_collect/transcripts_normalized/<video_id>.json`에 저장하여 비교 단계가 항상 같은 입력을 보도록 한다.

**Text Normalizer 트리거 — CLI 명시**:

정규화는 단독 멱등 단계로 분리한다. `collect transcripts` 또는 `collect process-audio`가 끝나도 운영자가 잊지 않고 정규화를 호출하도록, 두 가지 트리거 경로를 모두 제공한다.

```
tube-scout process normalize-transcripts
    --channel <alias>
    [--video-ids <comma-separated>]
    [--force]                # 기존 transcripts_normalized/ 결과를 덮어쓸 때만
```

이 명령은 `01_collect/transcripts/` 폴더 전체를 스캔해 ASR·API 출처 자막을 모두 동일 규칙으로 정규화한다. 멱등(같은 입력에 같은 출력). 또한 `collect transcripts`와 `collect process-audio` 명령은 기본적으로 끝에서 자동 호출(`--auto-normalize` 기본 on)하므로, 운영자가 별도 명령을 빠뜨려도 비교 단계 직전에 정규화가 보장된다.

**자막 출처 정책**: 자가 채널(비공개 다수)은 ASR로 자막을 생성하고, 다른 이의 채널(공개 영상만 분석)은 YouTube Data API caption 다운로드만 사용한다. 두 출처는 Text Normalizer를 거쳐 동일한 정규화 자막으로 수렴한다. 출처별 일관성 우선 정책(`--force-asr` 플래그로 공개 영상도 ASR 재처리)은 v0.5 이후 필요 시 도입하는 향후 옵션이며 본 idea에서는 구현하지 않는다. 자세한 결정 근거는 §12 항목 7 참조.

**자막 8지표**:

| ID | 지표 | 측정 대상 | 상태 |
|---|---|---|---|
| I-1 | SHA-256 hash | 글자 단위 완전 일치 | spec 007 구현 |
| I-2 | Cosine similarity (multilingual embedding) | 의미 유사도 | spec 007 구현 |
| I-3 | Word change rate | 어휘 변경률 | spec 007 구현 |
| I-4 | New term count | 신규 용어 수 | spec 007 구현 |
| I-5 | Duration diff | 재생시간 차 | spec 007 구현 |
| I-6 | Longest common segment | 시간축 최장 연속 일치 | **본 idea 완성** |
| I-7 | Segment run distribution | 일치 구간 길이 분포 | **본 idea 완성** |
| I-8 | Alignment density | 시간축 정렬 시 일치 밀도 | **본 idea 완성** |

**음원 지문**: 9번째 독립 신호. 두 영상의 chromaprint 사이 hamming distance(`services/audio_fingerprint.py:144 hamming_distance_per_int`) + 최적 정렬(`:178 best_alignment_hamming`). 자막 신호와는 별개 컬럼으로 `comparison_results`에 추가.

**매칭 모드**:

- **M-default** (spec 007 구현): 같은 교수 + 같은 과목 + 같은 주차 + 같은 차시, 연도만 다른 쌍.
- **M-nC2** (본 idea 완성): 한 교수의 모든 영상 쌍. 200영상이면 19,900쌍. spec 011 설계 그대로 — Layer A 길이 필터로 1차 cull → 후보 쌍에 대해서만 시간축 지표 계산.

**4계층 오탐 방어**:
- A. 길이 임계 — 연속 N초 미만 일치는 무시.
- B. 교수 baseline — 한 교수의 corpus에서 30% 이상 등장하는 n-gram 제거.
- C. 교차 교수 IDF — 학과·전체 corpus에서 흔한 용어 down-weight.
- D. 화이트리스트 — 검토자가 `CONFIRMED_DUPLICATE` 또는 `FALSE_POSITIVE` 라벨을 누적.

**재활용 4패턴 분류**: `whole-same-week` / `scattered-same-week` / `whole-different-week` / `scattered-different-week`. 본 idea에서는 음원 지문 신호와 결합하여 `re-recorded-same-content`(자막 유사, 음원 다름)와 `tail-update`(I-8이 영상 전반부에서 1.0, 후반부에서 0.0)라는 두 가지 새 패턴을 추가 검토한다(spec 011에 없던 분류).

---

### 7.6 사용자 시나리오 4건 처리 매핑

운영자가 직접 제기한 네 가지 시나리오를 본 idea의 도구가 어떻게 처리하는지 명시한다.

**시나리오 A — 길이 다른데 내용 비슷.**
음원 지문 한 줄 전체 비교는 길이 차로 다른 영상으로 판정. 단 chromaprint를 짧은 구간 단위로 자르면 부분 일치(예: "A의 03:20~04:50 = B의 12:10~13:40")를 찾을 수 있다. 강의 음성은 톤이 균일해 음원 지문이 음악만큼 날카롭지 않으므로, **자막 8지표를 1차, 음원 지문은 보조 증거**로 본다. 처리 가능.

**시나리오 B — 4조각 셔플.**
자막 청크 단위 비교에서 네 조각이 모두 일치 구간으로 잡힘. I-6(최장 연속 일치)은 작아지고 I-7(분포)은 커진다. spec 011의 `scattered-*` 패턴으로 자동 분류. 처리 가능.

**시나리오 C — 같은 대본 새 녹화.**
자막은 유사(I-2/I-3/I-6 모두 높음), 음원 지문은 다름. **이 조합 자체가 "재녹음 재활용"의 식별 서명**이 된다. 본 idea에서 신설할 `re-recorded-same-content` 패턴이 이 케이스를 잡는다.

**시나리오 D — 전반부 작년 자료 + 후반부 신규 20분.**
I-8 정렬 밀도가 영상 시간축 전반부에서 1.0 근처, 후반부에서 0.0 근처로 떨어지는 프로필을 그린다. 본 idea에서 신설할 `tail-update` 패턴이 이 형태를 식별. 보고서에는 시간축 프로필 차트를 함께 출력.

---

### 7.7 보고서 디자인

**대상**: 한 교수 단위 M-nC2 비교 결과. 정광석 교수 케이스로 가정하면 영상 200여 개, 비교 쌍 19,900개.

**보고서 톤 — "의심 근거 + 검토 우선순위"**:

이 보고서는 자동 판정 도구가 아니다. 교무 검토자가 한정된 시간 안에 어느 영상 쌍을 먼저 들여다볼지 결정하는 **우선순위화 자료**다. 따라서 보고서 표현은 "재활용 확정", "위반"처럼 단정적 라벨을 쓰지 않고, "의심 근거", "검토 우선순위 상위", "주의 필요"처럼 보류형으로 일관한다. 각 의심 쌍 항목은 다음 두 가지를 명시한다.

- **근거(evidence)**: 어떤 지표가 어떤 수치로 임계를 넘었는지(예: "I-2 cosine 0.91, I-6 longest contiguous 480초"). 운영자가 직접 원문 자막·시간축으로 추적할 수 있는 정량 근거만 제시.
- **반론(counter-evidence)**: 4계층 오탐 방어가 적용된 내역(예: "Layer B 교수 baseline에서 30% 제거 후 점수, Layer D 화이트리스트 미해당"). 점수가 높게 나온 이유와 동시에 false positive 가능성도 함께 표시.

**보고서 구조**:

**본문 (10~20쪽)**
- 표지 (채널, 교수명, 분석 기간, 영상 수, 비교 쌍 수, 생성 일시)
- 채널 요약 (과목별 영상 분포, 연도별 추이)
- 의심 등급 분포 (전체 19,900쌍 중 임계 이상 N쌍, 등급별 분포 차트)
- **의심 top-K 목록 (K=50 기본값, 운영자 조정)** — 쌍 ID, 두 영상 제목, 8지표 + 음원 지문 점수, 분류된 재활용 패턴, 시간축 미니 차트
- 패턴별 통계 (whole/scattered × same-week/different-week 4분면 + 신설 re-recorded / tail-update)
- 4계층 오탐 방어 적용 내역 (Layer A로 N쌍 cull, Layer B로 M쌍 down-weight, …)

**부록 (분량 가변)**
- 임계 이상 의심 쌍의 1:1 상세 페이지 (한 쌍당 한 페이지)
- 두 영상의 자막 정렬 뷰 (일치 구간 색상 하이라이트)
- 시간축 프로필 풀 차트
- 음원 지문 alignment 시각화

**부록 임계 정책**: 모든 19,900쌍을 부록에 넣지 않는다. 종합 의심 점수가 일정 임계 이상인 쌍만 부록에 포함하며, 임계는 운영자가 CLI 옵션으로 조정 가능(`--appendix-threshold 0.6` 형태). 임계 정책의 기본값은 spec 011 작업 중 실데이터로 튜닝.

**출력 형식**: HTML + PDF 동시 생성. spec 006의 bundle 인프라를 확장하여 새 템플릿 `professor_nC2_report.html`을 추가한다.

**CLI**:
```
tube-scout report content-reuse
    --channel <alias>
    --professor <name>
    --mode M-nC2
    [--appendix-threshold 0.6]
    [--format pdf | html | both]
    [--output <path>]
```

---

### 7.8 자막 export — knowledge base 구축용

**역할**: 자막 JSON을 깨끗한 텍스트 파일로 변환하여 외부 knowledge base 도구의 입력으로 사용.

**작업 범위**: 분석 파이프라인과 무관한 단순 변환. 한 CLI 명령으로 끝.

**변환 규칙**:
- 세그먼트 텍스트만 추출, 타임스탬프 제거(옵션으로 유지 가능)
- 연속된 세그먼트 사이 줄바꿈 정리
- 채움 표현·기침·"음~" 같은 ASR 잡음 패턴 제거(옵션)
- 출력 인코딩 UTF-8, BOM 없음

**CLI**:
```
tube-scout transcript export
    --video-id <id>
    [--format txt | md | jsonl]
    [--keep-timestamps]
    [--clean-fillers]
    [--output <path>]
```

**대량 export**:
```
tube-scout transcript export-bulk
    --channel <alias>
    [--video-ids-file <txt>]
    --output-dir <dir>
```

**입력 소스**: 본 idea의 ASR 출력(faster-whisper)뿐 아니라 공개 영상 YouTube Data API caption 출력도 같은 스키마라 그대로 받음. 즉 export CLI는 자막의 출처와 무관하게 동작.

---

## 8. DB 통합 구조

기존 `content_reuse.db`(13개 테이블) 구조를 그대로 활용하되, **메타데이터를 SQLite에도 적재**하여 보고서 생성 단계에서 SQL JOIN 한 번으로 모든 신호를 종합 조회할 수 있게 한다. JSON/Parquet 파일과 SQLite 테이블 간에는 native SQL JOIN이 불가능하므로, 보고서 생성기가 파일을 별도 메모리에 적재하고 매핑해야 하는 비효율을 제거한다.

**v4 마이그레이션 — 신규 테이블 2개 + 기존 테이블 ALTER**:

기존 테이블에 다음 컬럼이 추가된다:
- `processing_status`: `match_confidence` (TEXT), `caption_source_detail` (TEXT) 두 컬럼.
- `processing_status.status` enum 확장: `asr_in_progress`, `asr_failed` 두 값 추가. 구현 우선순위는 **Python frozenset(`VALID_PROCESSING_STATUSES`) 갱신을 1차로 적용**한다. 현재 schema의 `processing_status` 테이블은 CHECK constraint 없이 정의되어 있어, SQLite에서 기존 컬럼에 CHECK를 ALTER로 추가하기 어렵다(테이블 rebuild 필요). DB 단의 CHECK 도입은 별도 migration으로 분리하거나 본 idea에서 보류한다.
- `quality_results`: `asr_quality_flags` (TEXT, JSON 직렬화) 한 컬럼.
- `comparison_results`: §7.5 정의의 음원 지문 비교 컬럼(`audio_fp_hamming`, `audio_fp_best_offset`, `audio_fp_overlap_seconds`)과 이기종 자막 출처 구분 컬럼(`source_type_pair`).

신규 테이블 두 개:

```sql
CREATE TABLE IF NOT EXISTS channel_metadata (
    channel_id           TEXT PRIMARY KEY,
    channel_alias        TEXT NOT NULL,
    title                TEXT,
    country              TEXT,
    privacy_status       TEXT,
    source               TEXT NOT NULL,            -- 'takeout' / 'api' / 'manual'
    takeout_root_hint    TEXT,                     -- 최근 ingestion에 사용된 takeout 루트 (운영자 메모용)
    ingested_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_metadata (
    video_id             TEXT PRIMARY KEY,
    channel_id           TEXT NOT NULL,
    title                TEXT NOT NULL,
    duration_seconds     REAL,
    language             TEXT,
    category             TEXT,
    privacy_status       TEXT,                     -- 'public' / 'unlisted' / 'private'
    created_at           TEXT,                     -- 영상 생성 타임스탬프
    published_at         TEXT,
    source               TEXT NOT NULL,            -- 'takeout' / 'api'
    match_confidence     TEXT,                     -- 'high' / 'medium' / 'ambiguous'
    mp4_relative_path    TEXT,                     -- takeout 작업 디렉터리 기준 상대 경로
    ingested_at          TEXT NOT NULL,
    FOREIGN KEY (channel_id) REFERENCES channel_metadata(channel_id)
);

CREATE INDEX IF NOT EXISTS idx_video_meta_channel ON video_metadata(channel_id);
CREATE INDEX IF NOT EXISTS idx_video_meta_privacy ON video_metadata(privacy_status);
```

**mp4 경로 이식성 정책**:

`mp4_relative_path`는 채널별 통합 작업 디렉터리(예: `data/<channel_alias>/videos/`)를 기준으로 한 상대 경로다. ingestion 어댑터는 Takeout 분할 part(`3-001`, `3-002`, …)의 mp4들을 이 통합 디렉터리로 모은다(기본은 심볼릭 링크, `--copy` 옵션 시 복사). 런타임에 mp4 절대 경로가 필요한 코드는 `--takeout-dir <root>` CLI 인자 또는 환경변수 `TUBE_SCOUT_TAKEOUT_ROOT`와 결합해서 사용한다.

- 작업 디렉터리를 외장하드 등 다른 위치로 이전하면 DB는 손대지 않고 CLI 인자만 새 경로로 바꿔 실행한다.
- 심볼릭 링크 방식은 POSIX 호환 OS(NixOS·Gentoo Linux)에서만 검증. 다른 OS 호환성은 `[VERIFY]`.
- `channel_metadata.takeout_root_hint`는 최근 ingestion에 사용된 절대 경로를 단순 메모로 저장(운영자가 다음 실행 시 참고용). 런타임 결합에 사용되지 않는다.

**저장 위치 매핑 (수정)**:

| 데이터 | 저장 위치 | 비고 |
|---|---|---|
| 채널 메타 | `channel_metadata` (SQLite v4) + `channel_meta.json` | SQLite는 보고서 JOIN용, JSON은 분석 파이프 호환용 (이중 저장, source-of-truth는 SQLite) |
| 영상 메타 | `video_metadata` (SQLite v4) + `videos_meta.json` / `.parquet` | 동일 |
| 자막 raw + 세그먼트 | `01_collect/transcripts/<video_id>.json` | ASR 또는 API caption (대용량 텍스트는 SQLite에 BLOB로 넣지 않음 — 분석 파이프 호환) |
| **자막 정규화 결과** | `01_collect/transcripts_normalized/<video_id>.json` | **신규**, Text Normalizer 출력 |
| 자막 청크 MinHash | `fingerprint_hashes` (SQLite) | spec 007 구현 |
| 자막 비교 결과 | `comparison_results` (SQLite) | 본 idea에서 9개 컬럼 추가 (I-6/I-7/I-8 + 음원 지문 + 신설 패턴 + `source_type_pair`) |
| 자막 일치 구간 | `match_spans` (SQLite) | spec 011 미완 부분에서 완성 |
| 자막 품질 지표 | `quality_results` (SQLite) | spec 007의 Q-001~Q-005 + 본 idea 신규 `asr_quality_flags` JSON 컬럼(§7.4의 6종 플래그, 확장 가능 구조) |
| 음원 지문 | `audio_fingerprint` (SQLite v3) | master 머지 완료 |
| 처리 상태 | `processing_status` (SQLite) | `caption_source` + `match_confidence` 컬럼 활용 |
| 교수·기준 코퍼스 | `professor_pool`, `baseline_corpus`, `phrase_whitelist` | spec 011 |

**JOIN 예시 — 실제 컬럼명 기준**: 한 교수의 nC2 비교 결과를 영상 메타 + 두 종류 지문과 함께 조회. 컬럼명은 `src/tube_scout/storage/content_db.py:33, 462`의 정의를 그대로 사용한다.

```sql
SELECT
    v1.title              AS source_title,
    v1.privacy_status     AS src_privacy,
    v2.title              AS target_title,
    v2.privacy_status     AS tgt_privacy,
    cr.i2_cosine_similarity,
    cr.i6_longest_contiguous_seconds,
    cr.i7_distribution_dispersion,
    cr.i8_position_diversity,
    cr.audio_fp_hamming,
    cr.reuse_pattern,
    cr.matching_mode
FROM comparison_results cr
JOIN video_metadata v1 ON cr.source_video_id = v1.video_id
JOIN video_metadata v2 ON cr.target_video_id = v2.video_id
WHERE cr.matching_mode = 'M-nC2'
  AND cr.professor_id  = ?
ORDER BY cr.suspicion_score DESC;
```

**video_id 키 JOIN**으로 메타 + 자막 + 두 종류 지문 + 비교 결과를 모두 통합 조회 가능. JSON 파일은 분석 파이프 호환을 위해 유지하되 source-of-truth는 SQLite로 일원화한다. SQLite 적재는 Takeout ingestion 어댑터(§7.1)의 멱등 단계로 통합되어 JSON 갱신과 동시에 일어난다.

---

## 9. 개발 순서 (Phase 1 ~ 4)

**Phase 1 — Takeout ingestion + 오디오 추출 전처리 + 로컬 음원 지문**
- Takeout 메타데이터 CSV 통합 파서 (사용하지 않는 CSV 종류 명시적 무시)
- mp4 ↔ video_id 다중 휴리스틱 매핑 어댑터 (제목 → duration → 타임스탬프)
- ambiguous 매핑 큐 출력 → `01_collect/_ambiguous_mappings.csv` (운영자 편집형)
- 채널별 통합 작업 디렉터리 생성 + 심볼릭 링크 적재
- `channel_metadata`, `video_metadata` SQLite 테이블 신설 (v4 마이그레이션, `mp4_relative_path` + `takeout_root_hint`)
- `tube-scout collect takeout` CLI (`--takeout-dir`, `--copy` / 기본 심볼릭 링크)
- `tube-scout collect audio-extract` CLI (mp4 → 16 kHz mono wav, 분리 모드)
- `tube-scout collect fingerprint --source local` CLI (wav 입력)
- **sample rate 일관성 실측**: 동일 영상을 mp4 직접 / 16 kHz wav / 22.05 kHz wav 세 방식으로 산출한 chromaprint 비교 — 결과에 따라 기존 9개 지문 재산출 여부 결정
- 9개 takeout 영상에 대해 end-to-end 실행 + DB 검증 + 매핑 자동화율 실측

**Phase 2 — STT (faster-whisper) + Text Normalizer + 통합 파이프라인**
- faster-whisper 의존성 추가 (PEP 621 optional extra `asr`로 분리)
- `tube-scout collect transcripts --source asr` CLI + 옵션 + 프리셋 4종 (`poc-laptop` / `prod-a6000` / `prod-a6000-pool` / `cpu-fallback`)
- Whisper 환각 방어 기본값 강제(`--vad-filter on`, `condition_on_previous_text=False`, `compression_ratio_threshold=2.4`, `no-speech-threshold=0.6`)
- Text Normalizer 모듈 + `transcripts_normalized/` 저장 경로
- `tube-scout process normalize-transcripts` CLI (단독 멱등 단계)
- 통합 파이프라인 CLI `tube-scout collect process-audio` (영상별 [추출 → 지문 → STT → wav 삭제] 루프)
- `quality_results.asr_quality_flags` JSON 컬럼 추가(`quality_results` ALTER) — §7.4의 6종 ASR 품질 플래그
- PoC: 이 머신에서 5-1.임경민(105초) 영상 1개 추론, WER·소요 시간 실측
- 9개 영상 일괄 추론 (이 머신, 통합 파이프라인 사용) → 정규화된 자막 JSON 생성
- `prod-a6000-pool` 워커 풀 정책 구현(SQLite `processing_status` 큐 + 두 프로세스 dispatch)
- 운영 환경 검증은 GPU 서버 인계 시점에 별도

**Phase 3 — spec 011 미완 부분 완성 + nC2 분석 + 보고서**
- I-6 / I-7 / I-8 시간축 지표 구현 (실제 컬럼명: `i6_longest_contiguous_seconds`, `i7_distribution_dispersion`, `i8_position_diversity`)
- M-nC2 매칭 모드 구현 (200영상 = 19,900쌍 처리, per-pair checkpoint은 기존 `pair_checkpoint` 테이블 활용)
- 4계층 오탐 방어 (A/B/C/D)
- 4패턴 분류 + 신설 2패턴 (re-recorded / tail-update)
- 음원 지문 nC2 비교 추가, `comparison_results`에 `audio_fp_*` 컬럼 + `source_type_pair` 컬럼 ALTER
- **분석 실행 CLI**: 기존 `tube-scout content compare`(`cli/content.py:268`)와 `tube-scout content scan`(`cli/content.py:703`)에 `--mode M-nC2` 옵션 추가, 또는 신규 `tube-scout analyze content-reuse` 명령으로 분리. 분석 단계는 보고서 생성과 분리된 명시적 실행 단계로 둔다(보고서가 분석을 암묵 실행하지 않는다 — 재현성·디버깅 분리).
- `tube-scout report content-reuse` CLI + 보고서 템플릿(분석 산출물을 입력으로 받음)
- 9개 영상으로 mini-nC2 (= 36쌍) end-to-end 검증

**Phase 4 — 자막 export + spec 012(yt-dlp) 완전 삭제**
- `tube-scout transcript export` / `export-bulk` CLI
- spec 012(yt-dlp 어댑터) 완전 삭제:
  - `src/tube_scout/services/ytdlp_adapter.py`, `ytdlp_errors.py`, `srv3_parser.py` 및 관련 단위 테스트 삭제
  - `cli/collect.py`에서 `--source ytdlp` 분기 및 `_dispatch_ytdlp_transcripts` 함수 삭제
  - `pyproject.toml`에서 yt-dlp 관련 의존성·extras 제거
  - `flake.nix` devShell에서 yt-dlp 패키지 제거
  - 관련 specs/012 폴더 및 contracts 정리(기록 보존이 필요하면 git history만으로 충분)
- CLAUDE.md `Active Technologies` 갱신
- v0.5.0 release

각 Phase는 단독으로 의미를 가지므로 Phase 단위 머지 가능. 단 Phase 3은 Phase 2의 자막 JSON이 9개 영상에 모두 준비되어야 의미 있는 검증이 된다.

---

## 10. Scope OUT (영구 제외)

다음 항목은 본 idea와 후속 spec에서 다루지 않는다. 메모리 결정 사항이거나 본 idea에서 새로 결정한 사항.

- **OCR (슬라이드 시각 재활용 탐지)** — 메모리 `project_scope_decisions_20260506` 결정.
- **화자 분리 (게스트 강의 한 영상 두 교수 분리)** — 동 메모리.
- **외부(타교) 채널 ingestion** — 자교 채널만 분석. 외부 corpus 인덱스(spec 013)는 영구 폐기.
- **Cross-professor 재활용 탐지 (M-cross-prof 모드)** — 운영 데이터 누적 후 별도 idea로.
- **Takeout `시청 기록` / `검색 기록` HTML 활용** — 개인정보 영역, 본 분석과 무관.
- **클라우드 STT API (Google / Naver Clova / Azure)** — 로컬 우선 원칙.
- **자교 댓글 분석** — 메모리 `project_no_comments` 결정.

---

## 11. 별도 트랙 (이 idea와 무관)

다음 항목은 본 idea와 독립적이며 별도 일정으로 진행.

- **YouTube API Services quota 회신 (sample analyzed report 제출)** — 외부 커뮤니케이션, 메모리 `feedback_external_comms_no_takeout` 정책 준수.
- **idea6 (cross-spec consistency fix, D-1 ~ D-12)** — 운영 안정성 fix, 별도 트랙.
- **idea7 잔여 결함 (D-13 ~ D-17, L-1 ~ L-3)** — 운영 안정성 fix, 별도 트랙.
- **DTW(동적 시간 정렬) 도입** — 속도 변화 케이스 대응, 사례 발생 시 추가.
- **자카드 + 시퀀스 정렬 결합 점수** — 셔플 케이스 정교화, 운영 데이터 누적 후 결정.

---

## 12. 미해결 결정 사항 (spec 016 작성 전 합의 필요)

1. **spec 016 명칭 — 확정**: `016-takeout-local-asr-reuse` (2026-05-13 운영자 결정). 본 idea의 핵심이 Takeout 데이터를 기반으로 한 로컬 ASR + 재사용 판정이고 knowledge base export는 부가 산출물이라는 의도를 가장 명확히 드러낸다.

2. **부록 임계 기본값 — 확정**: 첫 운영 30일은 임계 없이 시각화(분포 히스토그램)로 운영자가 직접 임계를 정한 뒤, 그 뒤에 기본값을 확정한다(2026-05-13 운영자 결정).

3. **spec 012 코드 처리 — 확정: 완전 삭제.** yt-dlp는 대학이라는 공기관 운영 환경에 사용하기에 법적·정책적 적합성 문제의 소지가 크다는 운영자 판단(2026-05-13). 따라서 `_archive/`로의 보존도 채택하지 않고 master에서 코드·CLI·테스트·devShell 의존성·문서를 모두 제거한다. Phase 4 작업에 포함.

4. **A6000 ×2 동시 활용 정책 — 확정**: 비동기 워커 풀(2026-05-13 운영자 결정). cuda:0 전담 프로세스 + cuda:1 전담 프로세스가 SQLite `processing_status` 큐를 독립 소비. PoC는 cuda:0 단일 운용, 운영(GPU 서버 인계 시) `--preset prod-a6000-pool`. 세부 동작은 spec 016 spec.md에서 구현 디테일 확정.

5. **공개 영상 자막 다운로드 quota 회신 — 별도 트랙**: quota 증가 신청 진행 중. 샘플 보고서를 한 번 더 수정한 뒤 정확하게 메시지를 작성해서 대응 예정. 기본 방침은 신청한 quota를 그대로 받는 것. 외부 커뮤니케이션은 메모리 `feedback_external_comms_no_takeout` 정책 준수. 본 idea와 독립.

6. **신설 2패턴(re-recorded / tail-update) 우선순위 — 확정**: Phase 3 동시 출시(2026-05-13 운영자 결정). 음원 지문 인프라가 갖춰지는 시점에 함께 도입.

7. **자막 출처 정책 — 확정: 출처별 분리, force-asr 미구현.** 자가 채널은 ASR로 자막을 생성하고, 다른 이의 채널은 공개 영상만 분석 대상이므로 YouTube Data API caption 다운로드 결과만 사용한다(2026-05-13 운영자 결정). 공개 영상을 ASR로 재처리하는 `--force-asr` 옵션은 본 idea에서 구현하지 않으며, 향후 일관성 우선 분석이 필요해질 경우 별도 idea로 도입한다.

---

## 13. 산출물 요약

본 idea의 작업이 완료되면 다음이 운영자에게 제공된다.

- Takeout 디렉터리를 입력으로 받는 `tube-scout collect takeout` 명령 (메타데이터 SQLite + JSON 이중 적재, 통합 작업 디렉터리 + 심볼릭 링크 적재).
- mp4 → 16 kHz mono wav 추출 전처리 `tube-scout collect audio-extract` 명령 (분리 모드, 디버깅·재실행용).
- 추출된 wav에서 음원 지문을 일괄 산출하는 `tube-scout collect fingerprint --source local` 명령.
- faster-whisper로 자막을 생성하는 `tube-scout collect transcripts --source asr` 명령 (환각 방어 기본 강제, 프리셋 4종, 자동 정규화 옵션).
- **통합 파이프라인 명령 `tube-scout collect process-audio`** — 영상별 [WAV 추출 → 지문 → STT → WAV 삭제] 루프로 캐시 누적 없이 일괄 실행 (학과 전체 운영 경로).
- 자막 정규화 단독 명령 `tube-scout process normalize-transcripts`.
- **nC2 분석 실행 명령** — 기존 `tube-scout content compare`/`scan` 확장 또는 신규 `tube-scout analyze content-reuse`. 분석 결과는 `comparison_results` + `match_spans` + `pair_checkpoint`에 영속.
- 한 교수 단위 M-nC2 비교 보고서를 PDF/HTML로 생성하는 `tube-scout report content-reuse` 명령 (분석 산출물을 입력으로 받음, 분석을 암묵 실행하지 않음).
- 자막 JSON을 깨끗한 텍스트로 export하는 `tube-scout transcript export` 명령.
- spec 011 미완 부분(시간축 3지표 + M-nC2 + 4계층 + 4패턴 + 신설 2패턴)의 master 머지.
- `content_reuse.db` v4 마이그레이션 (메타데이터 SQLite 통합, `mp4_relative_path` 이식성 정책, `asr_quality_flags` JSON 컬럼 추가).
- spec 012(yt-dlp) 완전 삭제 — 코드·CLI·테스트·devShell·문서에서 제거(공기관 운영 적합성 사유).

운영자는 학과 전체 일괄 실행 시 **4단계**를 순서대로 실행한다:

1. `tube-scout collect takeout --takeout-dir <root> --channel <alias>` — 메타 적재 + 통합 작업 디렉터리 + 매핑.
2. `tube-scout collect process-audio --channel <alias> --preset prod-a6000-pool` — 영상별 [WAV 추출 → 지문 → STT → 정규화 → WAV 삭제] 루프.
3. `tube-scout analyze content-reuse --channel <alias> --professor <name> --mode M-nC2` — nC2 분석 실행, 결과를 `comparison_results`/`match_spans`에 영속.
4. `tube-scout report content-reuse --channel <alias> --professor <name> --mode M-nC2 --format both` — 영속된 분석 결과를 PDF/HTML로 렌더링.

단계별 디버깅이나 재실행이 필요한 경우 분리 CLI(`collect audio-extract`, `collect fingerprint`, `collect transcripts`, `process normalize-transcripts`, `content compare`/`scan`)를 개별 호출한다. knowledge base 구축은 `transcript export` 명령을 따로 호출한다.
