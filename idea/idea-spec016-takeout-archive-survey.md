# spec 016 입력 — Takeout archive 실측 정찰 보고서

**작성일**: 2026-05-15
**선행 문서**: `idea-spec016-takeout-ingest-defects.md` (§4 의 1번 항목을 본 문서에서 수행)
**처리 정책**: 본 보고서는 spec 016 정식 사양(`/speckit.specify`) 작성 시 두 번째 시드 입력으로 들어간다. 결함 1~5 와 본 보고서의 §5 추가 결함 6~9 는 spec 016 작성 시점에 일괄 수정한다.

**입력 데이터**: `data/takeout-20260511T130817Z-3-001/Takeout/` — 간호학과 채널 일부 archive(약 9.9 GB, 9개 mp4 + 채널 전체 메타데이터 csv). 사용자 확인(2026-05-15): 간호학과 한 채널의 **메타데이터상 영상 수는 2200개 이상** (본 정찰 측정치 2554 와 부합). 그중 9개를 본 머신에 샘플로 담아 둔 것이며, 나머지 archive part 들은 다른 곳에 보관 중. 부산보건대 22 학과 전체로 확장 시 메타상 영상 총수는 수만 개로 예상.

**검증 방법**: 코드를 한 줄도 건드리지 않고 archive 안 모든 폴더·파일의 컬럼 헤더, 데이터 분포, 분할 단위, mp4-메타 매칭 가능성을 Python `csv` 와 정규식으로 실측. 한글 multi-line quoted 필드 때문에 awk·sed 결과는 어그러지므로 본 보고서 수치는 모두 `csv` 모듈로 다시 측정한 값이다.

---

## 1. Takeout archive 전체 구조 — 실측

```
data/takeout-20260511T130817Z-3-001/Takeout/
└── YouTube 및 YouTube Music/
    ├── 구독정보/구독정보.csv                  (운영자 구독 채널 7개, 분석 무관)
    ├── 댓글/댓글.csv                           (댓글 1건, 자교 정책상 분석 제외)
    ├── 동영상/                                 (mp4 영상 본체 — 본 archive 에 9개)
    ├── 동영상 메타데이터/                      (csv 39개 — 3종 × 13파일, 본문 §3 참조)
    ├── 시청 기록/시청 기록.html                (운영자 개인 시청 기록, 분석 무관)
    ├── 시청 기록/검색 기록.html                (운영자 개인 검색 기록, 분석 무관)
    ├── 재생목록/재생목록.csv                   ("Watch later" 1건, 분석 무관)
    └── 채널/                                   (채널 자체 메타데이터 csv 5개)
```

archive 이름 규칙은 `takeout-YYYYMMDDTHHMMSSZ-<group>-<part>` 로 보인다 (`3-001` 부분). 본 archive 한 묶음에 영상 본체 9개와 **채널 전체 메타데이터 2554 영상분** 이 같이 들어 있다. 즉 archive 분할의 단위는 mp4 (대용량) 이고, 메타데이터는 모든 archive 에 중복 동봉되는지 또는 한 archive 에만 들어 있는지는 본 검증만으로 단정할 수 없다. spec 016 작성 시 archive 한 묶음만 풀어도 메타가 들어 있는지에 대한 가정을 명시할 필요가 있다 (`OPEN-Q-1`).

## 2. 코드 가정 vs 실측 대조표 (단일 권위 표)

`src/tube_scout/services/takeout_ingest.py` 의 모든 가정을 다음 한 표로 권위 정리한다. 결함 번호는 어제 결함 보고서의 1~5 를 잇는다.

### 2.1 디렉토리 가정

| 코드 상수 | 코드 값 | 실측 값 | 결과 |
|---|---|---|---|
| `_YT_SUBDIR` | `"YouTube 및 YouTube Music"` | `"YouTube 및 YouTube Music"` | **일치** |
| `_META_SUBDIR` | `"동영상 메타데이터"` | `"동영상 메타데이터"` | **일치** |
| `_CHANNEL_SUBDIR` | `"채널"` | `"채널"` | **일치** |
| `_VIDEO_SUBDIR` | `"동영상"` | `"동영상"` | **일치** |

디렉토리 이름은 한국어 Takeout 기준으로 코드 가정과 모두 맞다. 영어 Takeout 의 경우(현재 미검증) `Videos / Channel / Video metadata / YouTube and YouTube Music` 일 가능성이 높다 (`OPEN-Q-2`).

### 2.2 채널.csv 컬럼 가정 (결함 3 확정)

코드 `_CHANNEL_CSV_REQUIRED = {"채널 ID", "채널 이름"}` 가정과 실측 헤더 대조.

| 코드가 요구 | 실제 컬럼 | 상태 |
|---|---|---|
| 채널 ID | 채널 ID | **일치** |
| 채널 이름 | (없음) | **컬럼 자체 없음** — `채널 제목(원본)` 으로 대체 필요 |
| (요구 없음) | 채널 국가 | 보조 정보, 코드의 `row.get("국가","")` 가 못 잡는 형태 (결함 6) |
| (요구 없음) | 채널 태그 1 | 보조 정보, 채널 설명에 해당 |
| (요구 없음) | 채널 공개 상태 | 값 = `"공개"` (한글, 매핑 필요) |

샘플 행: `UCnh3tm9uQkyA260cAHfl9rg, KR, 부산보건대학교 간호학과 강의영상 채널, 부산보건대 간호학과, 공개`

채널 폴더에는 `채널.csv` 외에 부수 csv 4개가 더 있다 (`채널 URL 구성.csv`, `채널 기능 데이터.csv`, `채널 커뮤니티 운영 설정.csv`, `채널 페이지 설정.csv`). 모두 채널 ID 단일 행이며 분석 가치는 거의 없다. `채널 기능 데이터.csv` 의 `메타데이터의 기본 언어 = ko`, `동영상 기본 언어 = ko` 정도가 보조 정보로 활용 여지가 있다.

### 2.3 동영상*.csv 컬럼 가정 (결함 4 확정 + 추가 결함 발굴)

코드 `_VIDEO_CSV_REQUIRED` 가 요구하는 9개 컬럼 vs 실측 11개 컬럼 대조.

| 코드가 요구 | 실제 컬럼 | 상태 |
|---|---|---|
| 동영상 ID | 동영상 ID | **일치** |
| 동영상 제목 | 동영상 제목(원본) | **이름 다름** |
| 동영상 URL | (없음) | **컬럼 자체 없음** — `https://youtu.be/<id>` 규칙으로 도출 |
| 동영상 생성 타임스탬프 | 동영상 생성 타임스탬프 | **일치** |
| 근사치 길이(밀리초) | 근사치 길이(밀리초) | **일치** |
| 채널 ID | 채널 ID | **일치** |
| 카테고리 | 동영상 카테고리 | **이름 다름** |
| 공개상태 | 개인 정보 보호 | **이름 다름** + **값이 한글** (결함 7) |
| 오디오 언어 | 동영상 오디오 언어 | **이름 다름** |
| (요구 없음) | 동영상 제목(원본) 언어 | 보조 정보 |
| (요구 없음) | 동영상 설명(원본) 언어 | 보조 정보 |
| (요구 없음) | 동영상 상태 | 모두 `"처리됨"` — 별 의미 없음 |

핵심:

- **`동영상 URL` 컬럼은 실제로 존재하지 않는다**. 영상 ID 만 제공되며 URL 은 `https://youtu.be/<video_id>` 또는 `https://www.youtube.com/watch?v=<video_id>` 규칙으로 코드 측에서 만들어야 한다.
- **`개인 정보 보호` 의 실제 값은 한글** (`비공개`, `일부 공개`). 코드는 영어 `public/unlisted/private` 가정으로 한글 값을 받으면 즉시 None 으로 떨어뜨린다. 즉 본 데이터에서 코드가 `privacy_status` 를 정상 저장한 영상은 0개다 (결함 7).
- **`개인 정보 보호` 와 `동영상 상태` 가 별개 컬럼**이다. privacy 와 processing status 가 분리되어 있는 셈. 코드의 단일 `공개상태` 가정은 둘의 합성이 아니라 둘 중 하나(privacy)만을 의도한 것으로 보이며, 의미상 `개인 정보 보호` 컬럼에서 와야 한다.

### 2.4 분할 단위 (결함 5 보강) — **결정적 변경**

코드의 glob `meta_dir.glob("동영상*.csv")` 는 결함 5 가 의도한 "동영상.csv + 동영상(N).csv 13개" 만 잡는 것이 아니라 **같은 폴더의 `동영상 녹화*.csv` 와 `동영상 텍스트*.csv` 까지 잡는다**. 즉 영상 메타와 무관한 39개 csv 가 모두 video metadata 로 파싱 시도되며, 각각 `_VIDEO_CSV_REQUIRED` 컬럼이 없어 `ValueError` 가 발생한다 (결함 8).

실측 파일 인벤토리:

| 파일 시리즈 | 개수 | 컬럼 | 의미 | 행 수 (데이터) |
|---|---|---|---|---|
| `동영상.csv` + `동영상(1)~(12).csv` | 13 | `동영상 ID, 근사치 길이(밀리초), 동영상 오디오 언어, 동영상 카테고리, 동영상 설명(원본) 언어, 채널 ID, 동영상 제목(원본), 동영상 제목(원본) 언어, 개인 정보 보호, 동영상 상태, 동영상 생성 타임스탬프` | **영상 기본 메타** | 200 × 12 + 154 = 2554 |
| `동영상 녹화.csv` + `(1)~(12)` | 13 | `동영상 ID, 동영상 녹화 고도, 동영상 녹화 위도, 동영상 녹화 경도` | 영상 촬영 GPS (모두 0,0,0) | 동일 |
| `동영상 텍스트.csv` + `(1)~(12)` | 13 | `동영상 ID, 동영상 텍스트 생성 타임스탬프, 동영상 제목 텍스트 세그먼트 1, 동영상 텍스트 업데이트 타임스탬프` | **영상 제목 텍스트 (OCR 가능성)** — 자막 아님 | 동일 |

분할 단위는 **200 영상/파일** 이다. 본 파일(`동영상.csv`) 과 분할 파일들의 video_id 교집합은 **0** — 본 파일은 마지막 chunk 와 별도의 chunk 이다. 즉 13개 csv 가 모두 disjoint 인 결과, 채널 전체 영상 수 = **2554개** (사용자 확인 "2200개 넘는다" 와 일치).

여기서 "2554개" 와 archive 의 mp4 9개의 관계: **mp4 본체와 메타 csv 의 단위가 다르다**. 메타 csv 는 채널 전체 2554 영상분이 본 archive 한 묶음에 모두 들어 있고, 영상 본체(mp4)는 본 archive 에 9개만 있다. 나머지 2545 영상의 mp4 는 다른 archive part 에 분산되어 있으며(자교 한 학과가 약 2.4 TB 라는 사용자 확인과 부합), 본 머신에는 샘플 9개만 가져온 상태다. spec 016 의 적재 모듈은 따라서 다음 두 사실을 동시에 다뤄야 한다.

1. 한 archive 의 mp4 수 ≠ 채널의 영상 수. 한 archive 만 적재해도 메타 측은 채널 전체 2554 영상이 들어온다.
2. mp4 본체가 없는 영상(본 archive 기준 2545개)에 대해서는 ASR·sound footprint 단계가 자연스럽게 skip 되어야 하고, audit 에 "mp4 미동봉" 으로 기록된다. 추후 다른 archive part 가 풀리면 그때 ASR 이 실행된다.

코드의 dedup(`seen` 딕셔너리)이 우연히 작동하긴 하지만, glob 패턴이 `녹화/텍스트` 까지 잡는 한 컬럼 검증 단계에서 즉시 실패한다 (결함 8).

### 2.5 `_IGNORED_PATTERNS` 의 자막 동봉 가정 (정책 검증)

코드는 다음 7개 시리즈를 무시한다:

- `^동영상 녹화` — **타당** (GPS, 전부 0)
- `^동영상 텍스트` — **타당** (영상 제목 OCR/segmentation, 자막 아님)
- `^댓글` — **타당** (자교 정책)
- `^재생목록` — **타당** (운영자 개인 재생목록)
- `^구독정보` — **타당** (운영자 구독 채널)
- `^시청 기록` — **타당** (운영자 개인 시청 기록 — 자기 채널 영상 423개 + 외부 영상 1771개)
- `^검색 기록` — **타당** (운영자 개인 검색 기록)

무시 정책 자체는 모두 합리적이다. 다만 결함 8 (glob 너무 넓음) 과 본 정책이 서로를 보완하지 못하는 구조다: glob 이 모든 `동영상*` 을 잡고, 무시 정책은 `iterdir()` 단계의 폴더/파일 이름 매치이지 메타데이터 폴더 안에서 작동하지 않는다.

## 3. 자막 동봉 여부 — **자막은 동봉되지 않는다 + 향후 동봉 계획 없음 (사용자 확정)**

idea 문서 §3 의 가장 결정적인 질문에 대한 답: **Takeout archive 안에 자막 파일은 동봉되지 않는다.** 후보로 보였던 `동영상 텍스트(N).csv` 는 자막이 아니라 영상 제목 텍스트(`동영상 제목 텍스트 세그먼트 1`) 와 두 개의 타임스탬프(생성·업데이트)만 담고 있다. 영상 본문 자막 트랙(`.vtt`, `.srt`, `.sbv` 등)은 archive 어느 폴더에도 존재하지 않는다.

사용자 확정 사항 (2026-05-15): 모든 영상에 YouTube Studio 측 자막이 부재하며, **향후에도 YouTube 로부터 자막을 별도 다운로드받을 계획은 당분간 없다**. 즉 Takeout 으로 영상 본체를 일괄 받은 뒤 local LLM (faster-whisper, CTranslate2 백엔드) 으로 STT 하여 자막을 만들고 sound footprint 를 함께 추출하는 것이 spec 016 의 확정 방향.

귀결: 자교 강의 영상의 자막은 **반드시 faster-whisper ASR 로 새로 생성**한다. spec 013 의 ASR 경로(`collect transcripts --source asr`)가 폐기 대상이 아니라 **기본·유일 경로**가 된다. spec 016 의 자막 전략은 "Takeout 동봉 자막 → 없으면 ASR" 의 2단계가 아니라 "**ASR 단일 경로**" 다. 자막 source 분기 코드 (`--source asr` 대 `--source local` 대 `--source youtube`) 가 spec 016 시점에는 ASR 단일 분기로 단순화될 여지가 있다.

부수 확인:
- `동영상 텍스트` 의 행 수가 일부 분할(12)에서 64행으로 적은 이유는, 일부 영상에 텍스트 세그먼트가 추출되지 못한 상태 (영상 처음 몇 초에 텍스트가 없거나 OCR 실패) 일 가능성. 분석 보조용으로 향후 활용 여지는 있으나 spec 016 본 범위에서는 무시 정책 유지가 합리적.

## 4. mp4 ↔ 메타 매칭 가능성 — **9/9 정확 매칭**

본 archive 의 mp4 9개 모두 파일명(`stem`, 확장자 제거) 이 `동영상 제목(원본)` 컬럼 값과 **완전 일치**한다.

| mp4 파일명 | video_id | duration_ms |
|---|---|---|
| `10-1.정연진_기본간호학Ⅰ_2주차_1차시(간호학과)` | xA2D8Zlnevc | 1,678,000 |
| `10-2 정연진 기본간호학Ⅰ 1주차 2차시 (간호학과)` | lemcolIj5Ik | 1,574,000 |
| `14-2.장준희_비판적사고와간호과정_2주차_2차시(간호학과)` | 3ZrurYMmUrI | 2,133,000 |
| `19- 2 .허제은_ 아동간호학Ⅰ _3주차_ 2차시(간호학과)` | cNXjxwGGAvs | 2,949,000 |
| `22-1.강다연_우리말과글쓰기_2주차_1차시(간호학과)` | yKA5Hr-gGkM | 1,511,000 |
| `27-2.한종호_의사소통과팀워크_6주차_2차시(간호학과)` | f1AcdYPKBV0 | 1,302,000 |
| `42- 2. 박연경_ 정신간호학Ⅲ_ 6주차_ 2차시(간호학과더블)` | j4wJbRxcAQA | 1,322,000 |
| `5-1.임경민_간호연구세미나_8주차_1차시(간호학과)` | sUJbkkYzNGc | 106,000 |
| `9-2 리차드방 글로벌영어 1주차 2차시 (간호학과)` | _oYUS7rC2w0 | 1,310,000 |

귀결:

- 코드의 `decide_mapping(mp4, video_list)` evidence-score 매핑은 본 archive 에 대해서는 **자명한 정확 매칭** 만 다루면 된다. spec 013 의 fuzzy 매칭(Levenshtein 등) 은 본 archive 에서는 invoke 되지 않는다.
- 한 가지 주의: `5-1.임경민_간호연구세미나_8주차_1차시` 의 mp4 크기는 27.6 MB 인데 duration_ms 는 106초밖에 안 된다 (실제로 그 길이 영상이거나 partial export). meta duration 과 ffprobe duration 의 cross-check 가 ASR 품질 검증에 유용할 것.
- mp4 파일명에 공백·괄호·온점 등 특수문자가 다양하게 섞여 있다. ASR 처리 시 임시 wav 변환 명령에서 quoting 필수 (이미 해결되어 있는지 코드 측 검증 필요 — `OPEN-Q-3`).

## 5. 본 정찰로 추가 발굴된 결함 (어제 결함 1~5 에 이어짐)

### 결함 6 — `_parse_channel_csv()` 의 보조 컬럼 가정 불일치

`row.get("채널 이름", "")` 와 `row.get("국가", "")` 는 모두 존재하지 않는 컬럼명이다 (실제는 `채널 제목(원본)`, `채널 국가`). `get()` 의 default 가 `""` 이므로 silent fail 한다. 즉 ChannelMetadata 의 `title` 과 `country` 는 본 데이터에 대해 항상 None 으로 저장된다. **silent fail 이라 사용자가 인지하지 못하는 결함**이라는 점이 결함 3 보다 더 위험하다.

### 결함 7 — privacy_status 한글 → 영어 매핑 누락

`row["공개상태"]` (실제 컬럼은 `개인 정보 보호`) 의 값은 한글 `"비공개"`, `"일부 공개"`, (가능성: `"공개"`). 코드는

```python
if privacy not in ("public", "unlisted", "private"):
    privacy_status = None
```

으로 영어 값만 인정한다. 본 데이터 2554 영상 중 **2554개 전부가 privacy_status = None 으로 저장**된다 (`비공개` 2260 + `일부 공개` 294). 매핑 표:

| Takeout 한글 값 | 표준 영어 값 |
|---|---|
| `공개` | `public` |
| `일부 공개` | `unlisted` |
| `비공개` | `private` |

### 결함 8 — `meta_dir.glob("동영상*.csv")` 가 녹화/텍스트 csv 까지 흡수

§2.4 본문 참고. glob 패턴을 `동영상.csv` 와 `동영상(*).csv` 둘로 분리하거나, 헤더 검사 단계에서 `_VIDEO_CSV_REQUIRED` 미충족 시 즉시 raise 대신 **skip + 무시 audit** 으로 가도록 정책 결정 필요 (`OPEN-Q-4`).

### 결함 9 — 보조 컬럼의 무활용 (정보 등급)

실측 메타에는 코드가 안 쓰는 다음 정보가 들어 있다:

- `동영상 제목(원본) 언어` — 영상 제목의 언어 코드 (`ko`)
- `동영상 설명(원본) 언어` — 영상 설명의 언어 코드 (`ko`)
- `채널 국가`, `채널 태그 1`
- `동영상 텍스트(N).csv` 의 OCR 추정 텍스트 (자막 아님이지만 제목 외 보조 텍스트로 인덱싱 여지)

spec 016 본 범위에 포함시킬지 결정 필요 (`OPEN-Q-5`). 권장은 "본 범위 밖, 추후 separate spec".

### 결함 10 — 두 등록부 스키마 비교 결과 (결함 1 보강)

`channels.json` (`ChannelRegistration`) 과 `departments.json` (`Department`) 의 실측 스키마.

| 필드 | channels.json | departments.json | 비고 |
|---|---|---|---|
| alias | ★ | ★ | 양쪽 모두 primary key |
| channel_id | ★ **실제 값** | (없음) | channels 만 실제 channel_id 값을 저장 |
| channel_name / display_name | `channel_name` ★ | `display_name` ★ | 필드명은 다르지만 같은 정보 |
| OAuth env 변수 | (없음) | `channel_id_env`, `client_secret_env`, `api_key_env` ★ | departments 는 **env 변수명만** 저장 |
| OAuth 토큰 경로 | `token_path` ★ | (없음) | channels 만 토큰 파일 연동 |
| 시간 정보 | `registered_at`, `last_used_at` | `registered_at` | channels 가 last_used 도 추적 |

귀결:

- channels.json 은 **런타임 등록부** (실제 channel_id 와 OAuth 토큰 파일을 직접 보유, spec 003 OAuth 흐름과 spec 013 Takeout 적재 흐름이 모두 사용)
- departments.json 은 **운영자 인터페이스용 등록부** (agenix 환경변수 매핑 + display_name, spec 008 웹 관리 UI 가 사용). **Takeout 시대에는 OAuth env 3개가 dead column 이 된다.**

따라서 결함 1 의 통일 방향에는 두 갈래가 명확하게 갈린다 (`OPEN-Q-6`, §8 참고).

### 결함 11 — spec 003 `add-department` 의 OAuth 강제 (결함 2 보강)

`src/tube_scout/cli/admin.py:262` 의 `_check_envs_present(channel_id_env, client_secret_env, api_key_env)` 가 env 미정의 시 종료 코드 1 로 떨어진다. `--no-oauth-consent` 플래그는 이미 존재하지만 **env 검증 자체는 건너뛰지 않는다** (검증 후에 consent 만 skip).

해결 후보 3 가지:

- (a) 기존 명령에 `--takeout-only` 플래그 추가 → env 검증 + consent 둘 다 skip
- (b) `tube-scout admin add-department-takeout` 별도 명령 신설
- (c) **3개 env 옵션을 모두 optional 로 변경**. 명시되면 검증, 명시 안 되면 OAuth consent 단계도 자동 skip. spec 003 호환성 유지 + Takeout 호환 동시 지원

추천 (c). spec 016 결정 위임 (`OPEN-Q-7`, §8 참고).

## 6. 분석 활용 정보 인벤토리

| Takeout 파일/폴더 | 분석 활용 등급 | 비고 |
|---|---|---|
| `동영상/*.mp4` | **★★★ 필수** | 영상 본체. ASR·음성 지문·재사용 탐지 입력 |
| `동영상 메타데이터/동영상*.csv` (제외: 녹화/텍스트) | **★★★ 필수** | video_id, 제목, 길이, 생성 시각, privacy. 결함 4·7·8 수정 전제 |
| `채널/채널.csv` | **★★ 보조** | channel_id, 채널명(`채널 제목(원본)`), 국가. 결함 3·6 수정 필요 |
| `채널/채널 기능 데이터.csv` | ★ 참고 | 채널 기본 언어 정도 |
| `동영상 메타데이터/동영상 녹화*.csv` | × 제외 | GPS, 전부 0,0,0 |
| `동영상 메타데이터/동영상 텍스트*.csv` | × 제외 (현 범위) | 영상 제목 OCR 추정. 자막 아님. 추후 separate spec |
| `댓글/댓글.csv` | × 제외 | 자교 정책 (`project_no_comments.md`) |
| `재생목록/재생목록.csv` | × 제외 | 운영자 개인 재생목록 |
| `구독정보/구독정보.csv` | × 제외 | 운영자 구독 채널 |
| `시청 기록/시청 기록.html` | × 제외 | 운영자 개인 시청 기록 (자기 채널 영상 423 + 외부 1771) |
| `시청 기록/검색 기록.html` | × 제외 | 운영자 개인 검색 기록 |
| `채널/채널 URL/커뮤니티/페이지/...csv` | × 제외 | 채널 운영 설정 |

## 7. spec 016 작성에 들어갈 시사점 요약

다음 10개 사실이 spec 016 본문의 "Takeout 입력 데이터 매트릭스" 절을 추정 없이 채울 수 있는 실측 결론이다.

1. **자막은 Takeout 에 동봉되지 않고, 향후에도 YouTube 자막 다운로드 계획은 없다** (사용자 확정). ASR 가 **단일 경로**. spec 013 의 `--source asr` 가 spec 016 의 기본값이며, `--source youtube` 같은 분기는 spec 016 에서 제거 검토.
2. **채널 전체 영상 = 2554개 (사용자 확인 "2200+" 와 일치), 분할 단위 = 200 영상/csv, 분할 파일 = 13개** (본 파일 + 12개, 모두 disjoint). 영상 본체(mp4)는 archive part 별로 분산되며 본 archive 에 9개.
3. **archive 단위와 메타 단위가 다르다**: 한 archive 만 적재해도 메타는 채널 전체 2554 영상이 들어오고, mp4 가 없는 영상에 대해서는 ASR/지문 단계가 skip 되어야 한다 (audit "mp4 미동봉" 기록). 다른 archive part 가 풀리면 그때 ASR 재실행.
4. **mp4-메타 매칭은 본 archive 의 9개 모두에서 파일명-제목 정확 일치**. evidence-score fuzzy 매핑은 fallback 으로만 작동.
5. **결함 1~5 외에 결함 6~11 이 추가**: silent title/country fail (6), privacy 한글 매핑 누락 (7), meta glob 너무 넓음 (8), 보조 정보 무활용 (9), 두 등록부 스키마 차이 명확화 (10), `add-department` OAuth 강제 해결 후보 정리 (11). 모두 spec 016 의 적재 모듈 + admin CLI 재작성 범위.
6. **`_IGNORED_PATTERNS` 정책 자체는 모두 타당**. 정책은 유지, 다만 적용 위치(메타 디렉토리 내부 vs YT 디렉토리 직계)는 결함 8 해결과 함께 재검토.
7. **CSV multi-line quoted field 가 흔하다** — 영상 제목에 쉼표·줄바꿈·따옴표가 들어가는 케이스. 모든 파싱은 Python `csv` 모듈 또는 동등 RFC4180 quoting-safe 도구로 처리해야 한다 (awk·sed 금지). 본 보고서의 수치도 Python `csv` 로 측정한 값.
8. **`audio_extract.extract_wav_16k_mono()` 의 ffmpeg 호출은 list-argv 방식 (`subprocess.run(cmd, capture_output=True, text=True)`, `shell=False` 기본값)** 이므로 mp4 파일명의 공백·괄호·온점·한글이 모두 안전하게 처리된다 (실측 9개 mp4 의 파일명 특수문자 다양성과 무관하게 안전). 별도 fix 불필요. (당초 OPEN-Q-3 → 결론.)
9. **결함 8 의 glob 패턴 처리는 정확 분리가 권장 답**: `meta_dir.glob("동영상.csv")` + `meta_dir.glob("동영상(*).csv")` 두 패턴을 union 하거나 정규식 `^동영상(?:\(\d+\))?\.csv$` 매치. silent skip (`unknown_csv` audit) 은 사용자 메모리의 silent-skip 차단 정책과 충돌. (당초 OPEN-Q-4 → 결론.)
10. **두 등록부 통일/공존은 정책 결정 사항**: 코드/스키마 비교 결과 결함 10 으로 정리됨. 통일(channels.json 단일화) 과 공존(`admin list` 가 union 출력) 의 trade-off 가 분명히 갈리므로 사용자 결정 필요 — `OPEN-Q-6` 으로 유지.

## 8. 미결 질문 (spec 016 작성 시 사용자 결정 필요)

본 정찰로 코드·데이터로 답이 나온 질문은 위 §7 의 결론 8~9 로 이동했다. 다음 4 개만 사용자 결정으로 남는다.

| ID | 질문 | 본 정찰의 권장 |
|---|---|---|
| OPEN-Q-1 | 다중 archive (1-001, 2-001, 3-001 등) 환경에서 `동영상 메타데이터/` 폴더가 **모든 part 에 동봉**되는가, **한 part 에만 동봉**되는가. (본 정찰에서 archive root 에는 `archive_browser.html` 이나 README 등 단서가 없었다) | spec 016 본문 작성 직전에 다른 archive part 한 개를 추가로 풀어 확인 권장. 확인 전이라도 "메타 중복 동봉 가능성" 가정으로 가면 안전 (적재 시 INSERT OR IGNORE 로 멱등 보장) |
| OPEN-Q-2 | 영어 Takeout (`YouTube and YouTube Music/Videos/...`) 의 폴더·컬럼 이름 매핑을 spec 016 에 포함시킬지, 아니면 **한국어 export 단일 지원**으로 묶을지 | 부산보건대 22 학과 운영자 전원이 한국어 계정 사용 가능성이 높아 spec 016 본 범위는 **한국어 export 단일 지원** 권장. 영어 export 는 미래 spec |
| OPEN-Q-5 | `동영상 텍스트(N).csv` 의 영상 제목 OCR 텍스트를 분석에 통합할지 | **제외** 권장. 추후 separate spec |
| OPEN-Q-6 | 결함 10 (두 등록부) 통일 방향: (A) **channels.json 단일화** + departments.json 마이그레이션 + 웹 UI 코드 변경 / (B) **공존 유지** + `admin list` 가 두 등록부 union 출력 + 두 등록부 사이 alias 일관성 검증 추가 | (B) 가 변경 최소·spec 008 웹 UI 흐름 보존. 대신 alias 일관성 검증 누락 시 결함 1 의 "거짓말" 이 재발하므로 검증 로직은 spec 016 의 FR 로 명시 |
| OPEN-Q-7 | 결함 11 (`add-department` OAuth 강제) 해결: (a) `--takeout-only` 플래그 / (b) 별도 명령 신설 / (c) **3개 env 옵션 모두 optional** | (c) 권장. spec 003 호환 (env 명시 시 검증) + Takeout 호환 (env 생략 시 OAuth 단계 자동 skip) 양쪽 지원. 명령 수 증가 없음 |

## 9. 다음 단계 — `/speckit.specify` 진입

본 보고서 + 어제의 결함 보고서 두 개를 입력으로 `/speckit.specify` 진입. 두 문서를 시드로 넘겨 spec 016 본문(`specs/016-takeout-ingest/spec.md`) 을 작성한다. 본 정찰 결과로 spec 본문의 "Takeout 입력 데이터 매트릭스", "결함 인벤토리", "수정 범위 (FR)" 절은 추정 없이 실측에 근거해서 채울 수 있다.
