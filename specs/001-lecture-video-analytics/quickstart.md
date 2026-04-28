# Quickstart: Tube Scout

## Prerequisites

- Python 3.11+
- YouTube Data API v3 키 (Google Cloud Console에서 발급)
- (선택) YouTube Analytics API OAuth2 인증 — 시청 유지율 분석 시 필요
- (선택) Anthropic 또는 OpenAI API 키 — 댓글 감성분석/자막분석 시 필요

## Setup

```bash
# 1. 저장소 클론
git clone <repo-url> tube-scout && cd tube-scout

# 2. NixOS: devShell 진입 (flake.nix 기반)
nix develop

# 또는 uv로 직접 설치
uv sync

# 3. 환경변수 설정 (agenix 사용 시 devShell에서 자동 주입)
export YOUTUBE_API_KEY="your-api-key"
export ANTHROPIC_API_KEY="your-api-key"  # 선택
```

## Basic Usage

```bash
# 1. 프로젝트 초기화
tube-scout init --channel-id "UCxxxxxxxxxx" --professor "홍길동"

# 2. 데이터 수집
tube-scout collect all

# 3. 분석 실행
tube-scout analyze all

# 4. 리포트 생성
tube-scout report channel
tube-scout report video --video-id "xxxxxxxxxxx"

# 5. 상태 확인
tube-scout status
```

## Typical Workflow

```
init → collect videos → collect comments → collect transcripts
     → analyze sentiment → analyze transcript → analyze retention
     → report video → report channel
```

각 단계는 독립적으로 실행 가능하며, 이전 단계의 데이터가 있어야 다음 단계를 진행할 수 있다.

## Resuming Interrupted Collection

API 할당량 초과 등으로 수집이 중단된 경우:

```bash
# 중단 지점부터 자동으로 이어서 수집
tube-scout collect all

# 강제 전체 재수집
tube-scout collect all --force-refresh
```

## Output

- 데이터: `./data/` 디렉토리 (JSON + Parquet)
- 리포트: `./data/reports/` 디렉토리 (HTML 또는 Jupyter Notebook)
