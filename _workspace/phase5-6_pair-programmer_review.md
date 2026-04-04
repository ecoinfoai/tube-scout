# Phase 5-6 FR Traceability Review

**Reviewer**: pair-programmer
**Date**: 2026-04-04
**Scope**: FR-005, FR-015, FR-016

## FR Traceability Table

| FR | Description | Code Location | Test Location | Status |
|----|-------------|---------------|---------------|--------|
| FR-005 | 필터 결과 미리보기(dry-run) | `report.py:48-68` (_print_dry_run_table), `report.py:112-116` (video --dry-run), `report.py:177-179` (video early return), `report.py:510-514` (bundle --dry-run), `report.py:557-567` (bundle early return) | `TestReportVideoDryRun::test_dry_run_does_not_generate_reports`, `::test_dry_run_shows_count`, `TestReportBundleDryRun::test_bundle_dry_run_no_html_generated` | IMPLEMENTED |
| FR-015 | `--from-html` 옵션으로 기존 HTML에서 PDF 생성 | `bundle_report.py:112-191` (generate_from_html: HTML dir scan, body extract, bundle template render), `bundle_report.py:193-239` (_extract_html_body: html.parser), `report.py:515-519` (--from-html CLI option), `report.py:580-588` (from_html branch calls generate_from_html), `templates/bundle_from_html.html` (body_html \| safe rendering) | `TestExtractHtmlBody` (3 tests: body extraction, no-body, attributes), `TestGenerateFromHtml::test_from_html_filters_by_keyword`, `::test_from_html_missing_file_skipped`, `::test_from_html_no_matching_files_raises` | IMPLEMENTED |
| FR-016 | `--from-html` 모드에서 키워드/기간 필터 동작 | `bundle_report.py:137-143` (generate_from_html loads videos_meta, applies VideoFilterService.filter_videos with full VideoFilter, then matches {video_id}.html filenames) | `TestGenerateFromHtml::test_from_html_filters_by_keyword` (keyword filter applied, only matching video included in output) | IMPLEMENTED |

## Verification Details

**FR-015** spec: "report bundle은 기존 HTML 보고서 파일 디렉터리를 입력으로 받아 데이터 재분석 없이 PDF를 생성할 수 있어야 한다"
- generate_from_html() scans html_dir/{video_id}.html, extracts body via html.parser, renders into bundle_from_html.html template
- Missing/unparseable HTML files are skipped with logger.warning (line 150-163)
- Skipped list rendered in template (bundle_from_html.html:83-85, 109-113)
- No retention/segments data loading in from-html path -- confirms no data reanalysis

**FR-016** spec: "--from-html 모드에서도 키워드/기간 필터가 동작해야 한다"
- generate_from_html() loads videos_meta.json and applies VideoFilterService.filter_videos() with the same VideoFilter (line 137-138)
- Filtered results are matched to HTML files by video_id filename (line 149)
- Test confirms keyword="감염미생물학" filters correctly in from-html mode

**Bugfixes verified** (not FR-scoped but confirmed no regression):
- Empty keyword validation: video_filter.py:37-38
- Date parsing safety: video_filter_service.py:49-52, 65-78 (_parse_date)
- Video IDs strip: video_filter_service.py:59

## Summary

- **Total FR in scope**: 3
- **Implemented**: 3
- **Traceability rate**: 100% (3/3)
- **Tests**: 15/15 PASS (0.31s)

## Judgment

**PASS** -- FR-005, FR-015, FR-016 fully implemented with code and tests. No gaps found.
