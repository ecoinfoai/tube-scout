# Research: 보고서 필터링 및 PDF 종합 출력

## R-001: weasyprint PDF 생성 — 표지/목차/페이지번호

**Decision**: weasyprint + CSS `@page` 규칙으로 단일 HTML → PDF 변환

**Rationale**:
- weasyprint는 이미 pyproject.toml에 dependency로 포함됨
- CSS `@page`로 페이지 번호(`counter(page)` / `counter(pages)`) 제어 가능
- `page-break-before: always`로 영상별 페이지 구분 가능
- 목차는 HTML에서 앵커 링크로 구성하되, PDF 내부 링크로 변환됨
- 단일 HTML을 렌더링하므로 별도 PDF 병합 라이브러리 불필요

**Alternatives considered**:
- `pdfkit` (wkhtmltopdf 기반): NixOS에서 wkhtmltopdf 패키징이 복잡, weasyprint 대비 장점 없음
- `reportlab`: 프로그래밍 방식 PDF 생성 — 기존 Jinja2 템플릿 재사용 불가
- `fpdf2`: 한국어 폰트 지원이 약함

## R-002: weasyprint 시스템 의존성 (NixOS)

**Decision**: flake.nix devShell에 pango, glib, gobject-introspection, harfbuzz, fontconfig 추가

**Rationale**:
- weasyprint는 pango/gobject C 라이브러리에 의존
- 현재 NixOS 환경에서 `libgobject-2.0-0` 누락으로 import 실패 확인됨
- flake.nix의 `buildInputs`에 추가하면 `nix develop` 진입 시 자동 사용 가능

**Alternatives considered**:
- Docker 컨테이너: 개발 환경 분리 — 기존 flake.nix 워크플로우와 불일치
- playwright PDF (headless Chrome): 무거움, NixOS에서 Chromium 패키징 복잡

## R-003: 기존 HTML 수거 시 body 추출 방식

**Decision**: Python 표준 라이브러리 `html.parser`로 `<body>` 내용 추출

**Rationale**:
- 기존 개별 HTML은 완전한 문서(`<html><head>...`)이므로 병합 시 `<body>` 내용만 추출 필요
- 외부 의존성 추가 없이 표준 라이브러리로 충분
- 추출된 body를 bundle 템플릿의 영상별 섹션에 삽입

**Alternatives considered**:
- BeautifulSoup: 더 편리하지만 신규 dependency 추가 필요
- 정규식: fragile, 중첩 태그 처리 어려움

## R-004: plotly 차트의 PDF 렌더링

**Decision**: plotly 차트를 정적 SVG/PNG로 사전 렌더링하여 HTML에 삽입

**Rationale**:
- weasyprint는 JavaScript를 실행하지 않음 → plotly의 인터랙티브 차트가 PDF에서 빈 영역으로 표시
- `plotly.io.to_image()` 또는 `plotly.io.to_html(include_plotlyjs=False, full_html=False)` + static image fallback
- 기존 video_report.html 템플릿이 plotly JS를 사용하는 경우, bundle 용 PDF 템플릿에서는 정적 이미지로 대체

**Alternatives considered**:
- kaleido (plotly의 static export): 이미 plotly 설치 시 자동 포함 가능
- matplotlib로 차트 재생성: 기존 plotly 코드와 중복

## R-005: 필터링 로직 — videos_meta.json 구조

**Decision**: videos_meta.json에서 title, published_at 필드를 사용하여 필터링

**Rationale**:
- 현재 214개 영상의 메타데이터가 JSON으로 저장됨
- title 필드에 교수명/교과목/연도/주차 정보가 포함됨
- published_at 필드는 ISO 8601 형식
- 단순 `in` 연산자로 키워드 매칭 (clarify에서 확인됨)
- 날짜 비교는 문자열 비교로 충분 (ISO 형식이므로 사전순 = 시간순)

**Alternatives considered**:
- polars DataFrame으로 필터링: 214개 수준에서는 과잉, JSON 직접 처리가 적절
- SQLite 도입: 현재 데이터 규모에서 불필요
