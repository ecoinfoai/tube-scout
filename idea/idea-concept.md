# Tube Scout — 아이디어 전체 비교

## 버전별 목적

| 문서 | 목적 | 대상 사용자 | 상태 |
|------|------|-----------|------|
| idea.md | 단일 채널 기본 수집 + 리포트 | 교수 (개인) | v1 구현 완료 |
| idea2.md | Analytics 전체 수집 + LLM 분석 + 예측 | 교수 (개인) | v2 구현 완료 |
| idea3.md | 멀티채널 관리 + 제목 파싱 + 학과 보고서 | 교무과 (행정) | 미구현 |
| idea4.md | 자막 기반 콘텐츠 품질 + 재사용 탐지 | 교무과 + 교수 | 미구현 |

## 기능 매트릭스

| 기능 | idea (v1) | idea2 (v2) | idea3 | idea4 |
|------|:---------:|:----------:|:-----:|:-----:|
| **데이터 수집** | | | | |
| 영상 메타데이터 수집 | ✅ | ✅ 확장 | | |
| YouTube Analytics 수집 | △ Retention만 | ✅ 8개 리포트 | | |
| 자막 추출 | ✅ | ✅ | | ✅ 아카이브 |
| 댓글 수집 | ✅ | ✅ 대댓글 | | |
| Reporting API 벌크 | | ✅ | | |
| **인증/관리** | | | | |
| 단일 채널 OAuth | ✅ | ✅ | | |
| 멀티채널 토큰 관리 | | | ✅ | |
| agenix 연동 대비 | | | ✅ | |
| **검색/파싱** | | | | |
| 교수명 필터링 (단순) | ✅ | ✅ | | |
| 제목 구조 파싱 (교수/교과목/주차/차시) | | | ✅ | |
| search_clips.yaml 검색 | | | ✅ | |
| **분석** | | | | |
| 시청 유지율 Hotspot/Skip | ✅ | ✅ | | |
| LLM 감성 분석 | | ✅ | | |
| 한국어 NLP 로컬 감성 | | ✅ | | |
| 토픽-감성 맵핑 | | ✅ | | |
| LLM 자막 분할/요약 | | ✅ | | |
| EQS RACED 채점 | | ✅ | | ✅ Q-006 활용 |
| ARIMA/Prophet 예측 | | ✅ | | |
| 학사 달력 연동 | | ✅ | ✅ 준수율 | |
| 제목 이상 탐지 (V-001~V-009) | | | ✅ | |
| 영상 재사용 탐지 (자막 해시) | | | | ✅ |
| 연도별 콘텐츠 diff | | | | ✅ |
| 교육 품질 체크리스트 (Q-001~Q-006) | | | | ✅ |
| **보고서** | | | | |
| 영상별 리포트 (HTML/Notebook) | ✅ | ✅ | | |
| 채널 종합 리포트 | | ✅ 확장 | | |
| 댓글 인사이트 리포트 | | ✅ | | |
| 학과 보고서 (HTML/Excel/PDF) | | | ✅ | |
| 콘텐츠 품질 보고서 (HTML/Excel/JSON) | | | | ✅ |

## 의존 관계

```
idea (v1) ──→ idea2 (v2) ──→ idea3 ──→ idea4
  기본 수집      분석 확장      데이터 관리   콘텐츠 품질
                               │              │
                               └── 제목 파싱 ──→ 비교 대상 매칭
                               └── 메타데이터 ─→ 자막 아카이브
```

- idea3은 idea2 위에 구축 (멀티채널은 기존 수집 인프라 확장)
- idea4는 idea3에 의존 (제목 파싱 결과로 비교 쌍 매칭)
- idea4는 idea2의 EQS(RACED)를 Q-006에서 활용

## 기술 스택 누적

| 기술 | idea (v1) | idea2 (v2) | idea3 | idea4 |
|------|:---------:|:----------:|:-----:|:-----:|
| typer + rich (CLI) | ✅ | ✅ | ✅ | ✅ |
| google-api-python-client | ✅ | ✅ | ✅ | |
| youtube-transcript-api | ✅ | ✅ | | ✅ |
| pydantic v2 | ✅ | ✅ | ✅ | ✅ |
| pandas + polars | ✅ | ✅ | ✅ | |
| plotly | ✅ | ✅ | ✅ | ✅ |
| jinja2 | ✅ | ✅ | ✅ | ✅ |
| anthropic + openai | | ✅ | | ✅ 변경요약 |
| statsmodels + prophet | | ✅ | | |
| transformers + torch | | ✅ | | |
| sentence-transformers | | | | ✅ |
| ko-sroberta-multitask | | | | ✅ |
| openpyxl (xlsx) | | | ✅ | ✅ |
| PyYAML | | | ✅ | |
| difflib | | | | ✅ |

## 출력 데이터 저장 구조

모든 추출·분석 데이터는 `./output/` 아래에 실행 시점 기준 디렉터리로 저장한다. 이전 실행 결과를 보존하여 연도별·학기별 비교 시 재추출 없이 참조 가능.

```
output/
├── report-20260404-1211/                 ← 실행 시점 (YYYYMMDD-HHMM)
│   ├── raw/                              ← 수집 원본
│   │   ├── channels/{channel_id}/
│   │   │   ├── videos_meta.json
│   │   │   └── channel_meta.json
│   │   ├── transcripts/{video_id}.json
│   │   ├── analytics/{channel_id}/
│   │   └── retention/{video_id}.json
│   ├── parsed/                           ← idea3: 제목 파싱
│   │   └── {channel_id}/
│   │       ├── parsed_titles.json
│   │       ├── professors.json
│   │       └── courses.json
│   ├── validation/                       ← idea3: 이상 탐지
│   │   └── {channel_id}/
│   │       └── {year}_{semester}.json
│   ├── content/                          ← idea4: 콘텐츠 분석
│   │   └── {channel_id}/
│   │       ├── fingerprints.json
│   │       ├── comparisons/
│   │       ├── quality/
│   │       └── updates/
│   └── reports/                          ← 생성된 보고서
│       ├── department/
│       │   └── {channel_id}_{year}_{semester}.{html|xlsx|pdf}
│       └── content_quality/
│           └── {channel_id}_{year}_{semester}.{html|xlsx|json}
├── report-20260501-0900/                 ← 다음 실행
│   └── ...
└── latest -> report-20260501-0900/       ← 최신 실행 심볼릭 링크
```

- 각 실행은 독립 디렉터리로 완전히 격리
- `latest` 심볼릭 링크로 최신 결과 접근 편의
- 이전 실행 데이터를 참조하여 diff 비교 가능 (idea4 연도별 분석)
- `--output-dir` 옵션으로 오버라이드 가능

## 구현 순서

1. **idea3** — 멀티채널 토큰 + 제목 파싱 + 학과 보고서 + 이상 탐지
2. **idea4** — 자막 아카이브 + 재사용 탐지 + 콘텐츠 diff + 품질 체크 + 보고서
