# Research: 006-report-filter-pdf-bundle

## 1. 기존 필터링 인프라

**위치**: `models/video_filter.py`, `services/video_filter_service.py`

**재사용 100%**:
- `VideoFilter` (Pydantic): keyword(제목 substring), published_after/before, video_ids 지원. AND 로직.
- `VideoFilterService.filter_videos()`: 메타데이터 dict 순회, 조건별 필터링.
- `VideoFilterService.sort_videos()`: `"date"` (내림차순), `"course"` (교과목→주차), `"views"` (내림차순) 지원.

**Gap**: spec FR-013의 "게시일 오름차순"은 현재 `"date"`가 내림차순. `"date_asc"` 옵션 추가 필요.

---

## 2. 기존 보고서 인프라

**위치**: `reporting/bundle_report.py`

**현재 구현**:
- `BundleReportGenerator`: HTML 번들 생성 (표지, 요약, TOC, 영상별 섹션)
- 두 가지 모드: `generate()` (raw 데이터), `generate_from_html()` (기존 HTML 수확)
- `render_pdf()`: weasyprint lazy import, ImportError 시 None 반환
- Jinja2 템플릿, `@page` CSS (A4, 2cm 마진, 페이지번호, page-break)

**Gap 분석**:

| 요구사항 | 현재 상태 | 갭 |
|---------|----------|-----|
| FR-007 표지 | channel_id만 표시, duration 미포함 | channel_meta.json에서 채널명 로드, total_duration 추가 |
| FR-008 채널 요약 | 기본 통계만 (영상수, 총시간, 평균조회) | ParsedTitle 데이터로 교수/교과목 분포 추가 |
| FR-009 목차+페이지번호 | TOC 존재하지만 페이지번호 없음 | CSS `target-counter()` 추가 |
| FR-010 페이지번호 | `@page` CSS로 구현 완료 | 없음 |
| FR-011 페이지 구분 | `page-break-before: always` 구현 완료 | 없음 |
| FR-012 차트 분할 방지 | 테이블만 `page-break-inside: avoid` | 차트 컨테이너에도 추가 |

---

## 3. CLI 구조

**위치**: `cli/report.py`

**현재 구현**:
- `report_bundle_command`이 이미 `tube-scout report bundle`로 등록
- 옵션: `--keyword`, `--published-after`, `--published-before`, `--video-ids`, `--sort`, `--dry-run`, `--from-html`, `--title`, `--output`
- `--dry-run`은 미리보기만 표시, 생성과 연계 없음

**Gap**:
- FR-004/005: 미리보기 → 확인/취소 체인 없음. `typer.confirm()` 또는 Rich prompt 필요
- 미리보기 테이블에 view_count 미포함
- `--format` 옵션 없음 (항상 HTML→PDF 시도)

---

## 4. WeasyPrint 통합

**현재 사용 패턴**: `HTML(filename=str(path)).write_pdf(str(pdf_path))`

**PDF 기능 구현 방법**:
- TOC 페이지번호: `target-counter(attr(href url), page)` CSS
- PDF 북마크: `-weasy-bookmark-level` CSS 속성
- 차트 보호: `page-break-inside: avoid` on `.chart-container`

---

## 5. Decisions

| Decision | Rationale | Alternatives Rejected |
|----------|-----------|----------------------|
| 기존 VideoFilter/VideoFilterService 완전 재사용 | 필요한 필터링 기능이 이미 구현됨 | 새 필터 모델 생성 — 중복 |
| 기존 BundleReportGenerator 확장 | 구조가 적합, 갭이 incremental | 새 PDFBundleGenerator 생성 — 불필요한 분리 |
| `"date_asc"` 정렬 옵션 추가 | 기존 `"date"`는 내림차순, 보고서는 시간순이 자연스러움 | 기존 `"date"` 동작 변경 — 하위 호환성 파괴 |
| `--format pdf|html` 옵션 추가 | 명시적 형식 선택 | 항상 PDF 시도 — 사용자 제어 불가 |
| interactive confirmation 기본 활성화 | FR-005 요구사항, `--no-confirm`으로 비활성화 가능 | 항상 묻기 — 스크립트 실행 불편 |
