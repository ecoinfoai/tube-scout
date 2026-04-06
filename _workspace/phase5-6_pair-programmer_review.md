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

---

# Phase 4-5 FR Traceability Review (US2 + US3)

**Reviewer**: pair-programmer
**Date**: 2026-04-06
**Scope**: Phase 4-5 commit — US2 preview/confirm + US3 PDF bundle generation
**Changed files**:
- `src/tube_scout/cli/report.py` — --no-confirm, --format, view_count column, confirm flow, HTML fallback, weasyprint install guidance
- `src/tube_scout/reporting/bundle_report.py` — _load_channel_meta, _load_parsed_titles, _compute_channel_summary, channel_name/channel_summary in template render
- `src/tube_scout/reporting/templates/bundle_report.html` — channel_name on cover, total_duration on cover, channel summary section, .chart-container page-break-inside:avoid
- `src/tube_scout/reporting/templates/bundle_from_html.html` — same cover/channel_summary changes
- `tests/unit/test_report_cli_filter.py` — TestBundlePreviewUS2 (T010-T012)
- `tests/unit/test_bundle_report.py` — TestCoverPageUS3, TestChannelSummaryUS3, TestTocUS3, TestPageNumbersUS3, TestPageBreaksUS3, TestWeasprintFallbackUS3, TestFormatHtmlUS3

## Full FR Execution Path Traceability (FR-001~FR-017)

| FR | CLI Entry | Service/Generator | Template/Output | Status |
|----|-----------|-------------------|------------------|--------|
| FR-001 Keyword filter | `report_bundle_command` --keyword | VideoFilterService._matches: keyword in title | Filtered list | CONNECTED |
| FR-002 Date range filter | `report_bundle_command` --published-after/before | VideoFilterService._matches: date range check | Filtered list | CONNECTED |
| FR-003 AND logic | VideoFilter built with all params | _matches: sequential AND checks | Combined filter | CONNECTED |
| FR-004 Preview table | Lines 700-704: always shows preview before confirm | `_print_dry_run_table`: video_id, title, published_at, **view_count** | Rich table + count + duration | CONNECTED |
| FR-005 Confirm/cancel | Line 705-708: `typer.confirm("Generate report?")` | --no-confirm skips; "Cancelled" + exit(0) on decline | Interactive confirm/cancel | **CONNECTED** |
| FR-006 Single PDF | -> BundleReportGenerator.generate -> render_pdf | HTML -> weasyprint PDF | Single PDF | CONNECTED |
| FR-007 Cover page | _load_channel_meta, _compute_summary | cover: **channel_name**, filter_description, video count, **total_duration_minutes**, generated_at | Cover rendered | CONNECTED |
| FR-008 Channel summary | _load_parsed_titles + _compute_channel_summary | channel-summary section: professor_distribution, course_list | Channel summary page | CONNECTED |
| FR-009 Auto-generated TOC | bundle_report.html TOC section | `{% for video %}` anchor links + published_at | TOC with titles | CONNECTED |
| FR-010 Page numbers | @page CSS | `"p. " counter(page) " / " counter(pages)` | CSS rule | CONNECTED |
| FR-011 New page per video | .video-section CSS | `page-break-before: always` | CSS rule | CONNECTED |
| FR-012 No chart/table split | table + .chart-container CSS | `page-break-inside: avoid` on both | CSS rules | CONNECTED |
| FR-013 Three sort orders | --sort (date/date_asc/course/views) | VideoFilterService.sort_videos | Sorted list | CONNECTED |
| FR-014 Graceful data omission | Jinja conditionals | `{% if video.retention %}`, `{% if video.segments %}` | Sections skipped | CONNECTED |
| FR-015 PDF tool missing error | Line 748-752 | "weasyprint not available. Install weasyprint for PDF output." | Warning with guidance | CONNECTED |
| FR-016 HTML fallback | Line 741-742: `if format == "html": return` | render_pdf returns None -> HTML path | HTML saved | CONNECTED |
| FR-017 Existing data | _load_videos_meta | read_json(videos_meta.json) | Reads existing data | CONNECTED |

## Key Improvements Over Previous Review

1. **FR-005 CONNECTED** (was PARTIAL): `typer.confirm("Generate report?")` at line 706 provides interactive confirm/cancel. `--no-confirm` skips for automation.
2. **FR-007 cover complete** (was missing total_duration): Template line 116-118 adds total_duration on cover. Line 111 uses channel_name.
3. **FR-008 channel summary NEW**: _load_channel_meta, _load_parsed_titles, _compute_channel_summary in bundle_report.py. Template has professor_distribution + course_list.
4. **FR-012 strengthened**: `.chart-container { page-break-inside: avoid }` added.
5. **FR-015 improved**: Install guidance added to error message.

## Issues (Minor)

1. **Exit code inconsistency** (carried over): bundle uses exit(0) for 0-result, video uses exit(1). Design decision — not a correctness bug.
2. **Double filter execution**: report_bundle_command pre-filters at line 690, then gen.generate() filters again at bundle_report.py:83. Performance-only concern (negligible for 214 videos).
3. **--format default "pdf"**: If weasyprint not installed, default run shows warning. Previous implicit behavior was more forgiving. UX consideration only.

## FR Traceability

- **Connected**: 17/17
- **Rate**: 100%

## Judgment

**PASS** — FR traceability rate 100%. All 17 FRs have complete 3-layer execution paths. US2 (preview/confirm) and US3 (PDF bundle) fully implemented and tested (25/25 bundle, 18/18 cli_filter).
