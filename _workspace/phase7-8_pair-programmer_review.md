# Phase 7-8 FR Traceability Review

**Reviewer**: pair-programmer
**Date**: 2026-04-04
**Scope**: FR-011, FR-014

## FR Traceability Table

| FR | Description | Code Location | Test Location | Status |
|----|-------------|---------------|---------------|--------|
| FR-011 | 영상 정렬 기준 선택 (게시일순, 교과목-주차순, 조회수순) | `video_filter_service.py:69-90` (sort_videos: date/views/course), `video_filter_service.py:92-111` (_course_sort_key: regex parsing subject-week-session), `bundle_report.py:67` (generate uses sort_videos), `bundle_report.py:145` (generate_from_html uses sort_videos), `report.py:505-508` (--sort CLI option) | `TestSortVideos::test_sort_by_date_newest_first`, `::test_sort_by_views_descending`, `::test_sort_by_course_groups_by_subject`, `::test_sort_default_is_date` | IMPLEMENTED |
| FR-014 | 종합 보고서에 통계 요약 섹션 포함 (영상 수, 총 재생시간, 평균 조회수) | `bundle_report.py:308-327` (_compute_summary: video_count, total_duration_minutes, avg_views, total_likes), `bundle_report.py:80` (generate calls _compute_summary), `bundle_report.py:88` (summary passed to template), `bundle_report.html:117-140` (Summary section with metric cards) | `TestComputeSummary::test_summary_video_count`, `::test_summary_total_duration`, `::test_summary_average_views`, `::test_summary_total_likes`, `::test_summary_in_html_output` | IMPLEMENTED |

## Verification Details

**FR-011** spec: "시스템은 영상 정렬 기준을 선택할 수 있어야 한다 -- 게시일순(기본값), 교과목-주차순, 조회수순"
- date: sorted by published_at desc (newest first) -- default
- views: sorted by view_count desc
- course: regex `(\d+)\s*주차\s*(\d+)\s*차시` extracts week/session, sort key = (subject, week, session)
- Both generate() and generate_from_html() delegate to VideoFilterService.sort_videos()
- Test verifies exact ordering for all 3 sort modes + unknown fallback to date

**FR-014** spec: "종합 보고서(bundle)에 필터 대상 영상의 통계 요약 섹션을 포함할 수 있어야 한다"
- _compute_summary() calculates: video_count, total_duration_minutes, avg_views, total_likes
- Template renders Summary section between cover and TOC (bundle_report.html:117-140)
- Spec says "표지 다음에" -- template confirms cover (page-break-after) then summary then TOC
- Test verifies computation accuracy + HTML presence

**Note**: BundleReportGenerator._sort_videos (line 284-306) is now dead code, superseded by VideoFilterService.sort_videos. Not a traceability issue but a cleanup candidate.

## Summary

- **Total FR in scope**: 2
- **Implemented**: 2
- **Traceability rate**: 100% (2/2)
- **Tests**: 9/9 PASS (0.13s)

## Judgment

**PASS** -- FR-011, FR-014 fully implemented with code and tests. No gaps found.
