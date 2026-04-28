# CLI Command Contract: tube-scout

**Branch**: `001-lecture-video-analytics` | **Date**: 2026-04-01

## Command Structure

```
tube-scout <command> [options]
```

## Commands

### `tube-scout init`

프로젝트 설정 초기화. 채널 ID와 교수명을 설정 파일에 저장.

```
tube-scout init --channel-id <CHANNEL_ID> --professor <NAME>
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--channel-id` | Yes | - | YouTube 채널 ID (UC로 시작) |
| `--professor` | Yes | - | 필터링 대상 교수명 |
| `--data-dir` | No | `./data` | 데이터 저장 디렉토리 |

**Output**: `config.json` 생성, 성공 메시지
**Exit codes**: 0 (성공), 1 (잘못된 채널 ID 형식)

---

### `tube-scout collect`

YouTube API로 데이터 수집. 서브커맨드로 수집 범위 지정.

```
tube-scout collect [videos|comments|transcripts|retention|all]
```

| Subcommand | Description |
|------------|-------------|
| `videos` | 영상 목록 + 기본 메트릭 수집 |
| `comments` | 영상 댓글 수집 |
| `transcripts` | 자막 수집 |
| `retention` | 시청 유지율 데이터 수집 (Analytics API 필요) |
| `all` | 위 전체를 순차 실행 |

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--force-refresh` | No | false | 체크포인트 무시, 전체 재수집 |
| `--video-id` | No | - | 특정 영상만 수집 |

**Output**: 수집 진행률 (rich progress bar), 완료 요약
**Exit codes**: 0 (성공), 1 (인증 오류), 2 (할당량 초과 — 체크포인트 저장 후 종료)

---

### `tube-scout analyze`

수집된 데이터를 분석.

```
tube-scout analyze [sentiment|transcript|retention|eqs|forecast|all]
```

| Subcommand | Description |
|------------|-------------|
| `sentiment` | 댓글 감성/토픽/질문 분석 |
| `transcript` | 자막 챕터 분할, 요약, 난이도 예측 |
| `retention` | Rewatch Hotspot / Skip Zone 식별 |
| `eqs` | 교육 품질 점수(RACED) 산출 |
| `forecast` | 시계열 예측 및 이상 탐지 |
| `all` | 위 전체를 순차 실행 |

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--video-id` | No | - | 특정 영상만 분석 |
| `--sentiment-backend` | No | `llm` | 감성분석 백엔드 (`llm` / `local` / `skip`) |

**Output**: 분석 진행률, 완료 요약
**Exit codes**: 0 (성공), 1 (데이터 없음 — 먼저 collect 필요)

---

### `tube-scout report`

분석 결과 리포트 생성.

```
tube-scout report [video|channel]
```

| Subcommand | Description |
|------------|-------------|
| `video` | 영상별 개별 리포트 |
| `channel` | 채널 종합 리포트 |

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--video-id` | No | - | 특정 영상 리포트 (video 서브커맨드 시) |
| `--format` | No | `html` | 출력 형식 (`html` / `notebook`) |
| `--output-dir` | No | `./data/reports` | 출력 디렉토리 |

**Output**: 리포트 파일 경로
**Exit codes**: 0 (성공), 1 (분석 데이터 없음)

---

### `tube-scout status`

현재 수집/분석 상태 요약 표시.

```
tube-scout status
```

**Output**: 채널 정보, 수집된 영상 수, 분석 완료 현황, 마지막 수집 시각 등 테이블 형태

---

### `tube-scout list`

수집된 영상 목록 표시.

```
tube-scout list [--sort <field>] [--limit <N>]
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--sort` | No | `published_at` | 정렬 기준 (`published_at` / `view_count` / `like_count`) |
| `--limit` | No | 20 | 표시 개수 |

**Output**: 영상 목록 테이블 (ID, 제목, 업로드일, 조회수, 분석 상태)

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `YOUTUBE_API_KEY` | Yes | YouTube Data API v3 키 |
| `YOUTUBE_OAUTH_TOKEN` | No* | YouTube Analytics API OAuth 토큰 (retention 수집 시 필수) |
| `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` | No* | LLM 감성분석/자막분석 시 필수 |

## Configuration File

`config.json` (프로젝트 루트 또는 `--data-dir` 내):

```json
{
  "channels": [
    {
      "channel_id": "UCxxxxxxxxxx",
      "professor_name": "홍길동"
    }
  ],
  "settings": {
    "data_dir": "./data",
    "sentiment_backend": "llm",
    "default_report_format": "html"
  }
}
```

> `channels`가 리스트 구조이므로 v2에서 복수 채널/교수 확장 시 코드 변경 최소화.
