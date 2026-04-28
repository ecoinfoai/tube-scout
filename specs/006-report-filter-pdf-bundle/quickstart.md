# Quickstart: 006-report-filter-pdf-bundle

## 이 feature가 하는 것

기존 `tube-scout report bundle` 명령을 확장하여:
1. 영상 필터링 → 미리보기 → 확인 → PDF 번들 생성 워크플로우 구현
2. PDF에 표지(채널명+필터조건), 채널 요약, 목차(페이지번호), 페이지번호 추가
3. weasyprint 미설치 시 HTML 폴백

## 기존 코드 재사용율: ~80%

대부분의 인프라가 이미 존재합니다:
- `VideoFilter` + `VideoFilterService`: 필터링/정렬 100% 재사용
- `BundleReportGenerator`: HTML 번들 생성 파이프라인 재사용
- `render_pdf()`: weasyprint 통합 재사용
- CLI 옵션: `--keyword`, `--published-after/before`, `--dry-run` 등 재사용

## 수정이 필요한 파일 (5개)

| 파일 | 변경 내용 |
|------|----------|
| `services/video_filter_service.py` | `"date_asc"` 정렬 옵션 추가 (3줄) |
| `reporting/bundle_report.py` | 채널명 로드, 채널 요약 데이터 계산, template context 확장 |
| `reporting/templates/bundle_report.html` | 표지 확장, 채널 요약 페이지, TOC 페이지번호 CSS |
| `reporting/templates/bundle_from_html.html` | 위와 동일한 템플릿 변경 |
| `cli/report.py` | `--format`, `--no-confirm` 옵션, 미리보기→확인 흐름, view_count 컬럼 |

## 개발 순서 제안

```
Phase 1: date_asc 정렬 + 미리보기 확인 흐름 (US1, US2)
Phase 2: PDF 템플릿 확장 — 표지, 채널 요약, TOC 페이지번호 (US3, US5)
Phase 3: 정렬 옵션 + format 옵션 (US4, FR-015/016)
Phase 4: edge cases + adversary tests
```

## 테스트 실행

```bash
uv run pytest tests/unit/test_video_filter.py tests/unit/test_bundle_report.py tests/unit/test_report_cli_filter.py -x
```
