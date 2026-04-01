# Quickstart

5분 안에 Tube Scout를 설정하고 첫 분석을 실행하는 가이드입니다.

## 1. 사전 준비

- Python 3.11 이상
- YouTube Data API v3 키 ([Google Cloud Console](https://console.cloud.google.com/apis/credentials)에서 발급)

## 2. 설치

```bash
git clone https://github.com/ecoinfoai/tube-scout.git
cd tube-scout

# NixOS 사용자
nix develop

# 또는 uv로 직접 설치
uv sync
```

## 3. 환경변수 설정

```bash
# YouTube Data API 키 (필수)
export YOUTUBE_API_KEY="AIzaSy..."

# LLM API 키 (감성분석, 자막분석 시 필요 — 선택)
export ANTHROPIC_API_KEY="sk-ant-..."
# 또는
export OPENAI_API_KEY="sk-..."
```

> NixOS + agenix 사용 시 `flake.nix` devShell에서 자동 주입됩니다.

## 4. 프로젝트 초기화

```bash
tube-scout init \
  --channel-id "UCxxxxxxxxxxxxxxxxxx" \
  --professor "홍길동"
```

- `--channel-id`: YouTube 채널 ID (UC로 시작하는 24자 문자열)
- `--professor`: 영상 제목에서 필터링할 교수명

채널 ID는 YouTube 채널 페이지 URL에서 확인하거나, "YouTube 채널 ID 찾기" 도구를 사용하세요.

## 5. 데이터 수집

```bash
# 영상 목록 + 기본 메트릭 수집
tube-scout collect videos
```

실행하면 채널의 모든 영상 중 제목에 "홍길동"이 포함된 영상을 자동으로 필터링하고, 조회수/좋아요/댓글 수/영상 길이를 수집합니다.

## 6. 결과 확인

```bash
# 수집된 영상 목록 보기
tube-scout list

# 조회수 기준 상위 10개
tube-scout list --sort view_count --limit 10

# 현재 상태 확인
tube-scout status
```

## 7. 추가 데이터 수집 (선택)

```bash
# 댓글 수집
tube-scout collect comments

# 자막 수집
tube-scout collect transcripts

# 시청 유지율 수집 (채널 소유자 OAuth 필요)
tube-scout collect retention

# 또는 한번에 전부 수집
tube-scout collect all
```

## 8. 분석 실행

```bash
# 시청 유지율 분석 (되감기 구간/건너뛰기 구간 식별)
tube-scout analyze retention

# 댓글 감성/토픽/질문 분석
tube-scout analyze sentiment

# 자막 챕터 분할 + 난이도 예측
tube-scout analyze transcript

# 또는 한번에 전부 분석
tube-scout analyze all
```

## 9. 리포트 생성

```bash
# 특정 영상 리포트
tube-scout report video --video-id "xxxxxxxxxxx"

# 채널 종합 리포트
tube-scout report channel

# Jupyter Notebook으로 내보내기
tube-scout report video --format notebook
```

생성된 리포트는 `data/reports/` 디렉토리에 저장됩니다. HTML 파일을 브라우저로 열어 확인하세요.

## 전체 워크플로우 요약

```
init → collect videos → list (확인)
     → collect comments → analyze sentiment
     → collect transcripts → analyze transcript
     → collect retention → analyze retention
     → report video / report channel
```

각 단계는 독립적으로 실행할 수 있으며, 이전 단계의 데이터가 없으면 안내 메시지가 표시됩니다.

## API 할당량 초과 시

YouTube Data API는 일일 10,000 units 제한이 있습니다. 수집 중 할당량이 초과되면 진행 상황이 자동 저장되고 중단됩니다.

```bash
# 다음 날 이어서 수집 (자동 resume)
tube-scout collect videos

# 처음부터 다시 수집하려면
tube-scout collect videos --force-refresh
```
