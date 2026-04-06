# Layer 2: Module Contract Audit Results

## 요약

| 패키지 | 모듈 수 | 미사용 API | 내부 API 노출 | 계약 불일치 |
|--------|---------|-----------|-------------|-----------|
| models | 10 | 8 | 0 | 2 |
| services | 16 | 3 | 0 | 2 |
| storage | 3 | 1 | 0 | 0 |
| reporting | 7 | 0 | 0 | 1 |
| cli | 10 | 0 | 4 | 0 |
| visualization | 1 | 0 | 0 | 0 |
| output | 1 | 0 | 0 | 0 |

**총 발견**: 미사용 public API 12건, 내부 API 외부 노출 4건, 계약 불일치 5건

---

## A. API Surface

### models/analytics.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `VALID_REPORT_TYPES` | **미사용** | 정의만 존재, 외부 참조 없음 |
| `AnalyticsReport` | **미사용** | 어떤 서비스/CLI에서도 인스턴스화하지 않음 |
| `DailyMetrics` | **미사용** | 정의만 존재, YouTubeAnalyticsService가 dict 반환 |
| `TrafficSource` | **미사용** | 동일 |
| `DemographicGroup` | **미사용** | 동일 |
| `GeographyData` | **미사용** | 동일 |
| `DeviceData` | **미사용** | 동일 |
| `PlaybackLocation` | **미사용** | 동일 |
| `SubscriberChange` | **미사용** | 동일 |
| `ReportingJob` | 사용 | youtube_reporting.py |
| `VALID_JOB_STATUSES` | 내부만 사용 | analytics.py 내 validator |

**주요 발견 [WARNING]**: `DailyMetrics`, `TrafficSource` 등 7개 Pydantic 모델이 정의되어 있지만, `YouTubeAnalyticsService`가 plain dict를 반환하므로 사용되지 않음. 타입 안전성 계약이 깨져 있음.

### models/channel.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `Channel` | **미사용** | 어디서도 import/인스턴스화하지 않음 |

**발견 [INFO]**: `Channel` 모델 정의 존재하지만 서비스/CLI에서 사용하지 않음. `YouTubeDataService.get_channel_info()`는 plain dict 반환.

### models/comment.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `Comment` | **미사용** | 어디서도 import하지 않음 |

**발견 [INFO]**: Comment 모델이 정의되어 있지만, 댓글 수집/분석 파이프라인이 모두 plain dict로 동작.

### models/config.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `get_device()` | 사용 | sentiment.py (`_load_local_pipeline`) |
| `RateLimitProfile` | 사용 | rate_limiter.py, config.py 내부 |
| `TRANSCRIPT_PROFILE` | 사용 | config.py default factory |
| `YOUTUBE_API_PROFILE` | 사용 | config.py default factory |
| `StageResult` | 사용 | cli/collect.py |
| `PipelineResult` | **미사용** | 정의만 존재, collect_all이 StageResult 리스트 사용 |
| `ChannelConfig` | 사용 | cli/main.py |
| `Settings` | 사용 | cli/main.py |
| `AppConfig` | 사용 | cli/collect.py, cli/report.py, cli/status.py, cli/analyze.py |
| `CollectionState` | 사용 | storage/checkpoint.py, cli/collect.py |
| `CalendarEvent` | 사용 | 내부 (AcademicCalendar) |
| `AcademicCalendar` | 사용 | cli/main.py |
| `ChannelRegistration` | 사용 | services/auth.py |
| `Report` | **미사용** | 어디서도 import하지 않음 |
| `VALID_EVENT_TYPES` | 내부만 사용 | config.py validator |

### models/parsed_title.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `VALID_CATEGORIES` | 내부만 사용 | validator |
| `ParsedTitle` | 사용 | title_parser, search_service, validator, cli/report, cli/search_cli, cli/validate_cli, reporting/department_report |

### models/report.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `VALID_WEEK_STATUSES` | 내부만 사용 | validator |
| `DepartmentOverview` | 사용 | reporting/department_report, reporting/excel_export |
| `ProfessorDetail` | 사용 | reporting/department_report, reporting/excel_export |
| `ComplianceMatrix` | 사용 | reporting/department_report, reporting/excel_export |

### models/search.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `SearchFilter` | 사용 | search_service.py |
| `ExcludeRule` | 사용 | search_service.py |
| `SearchQuery` | 사용 | search_service.py |

### models/validation.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `VALID_SEVERITIES` | 내부만 사용 | validator |
| `VALID_RULE_PATTERN` | 내부만 사용 | validator |
| `ValidationFinding` | 사용 | services/validator, cli/validate_cli |

### models/video.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `Video` | 사용 | reporting/department_report, cli/report |
| `Video.title_contains_professor()` | **미사용** | 메서드 정의만 존재, 사용 안 됨 |
| `ViewingPattern` | **미사용** | 어디서도 import 안 됨 |
| `TranscriptSegment` | **미사용** | 어디서도 import 안 됨 |
| `QualityScore` | **미사용** | EQSService가 dict 반환 |
| `Forecast` | **미사용** | ForecasterService가 dict 반환 |

### models/video_filter.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `VideoFilter` | 사용 | video_filter_service, bundle_report, cli/report |

### models/__init__.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `VideoFilter` (re-export) | **미확인** | 직접 import가 models.video_filter에서 이루어짐 |

---

### services/auth.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `SCOPES` | 내부 사용 | |
| `TOKEN_FILE` | 내부 사용 | |
| `authenticate()` | 사용 | `build_data_client`, `build_analytics_client`, `build_reporting_client` |
| `build_data_client()` | 사용 | cli/collect.py |
| `build_analytics_client()` | 사용 | cli/collect.py |
| `build_reporting_client()` | 사용 | cli/collect.py |
| `load_registry()` | 사용 | 내부 + `save_registry`, `authenticate_channel` |
| `save_registry()` | 사용 | `register_channel`, `revoke_channel`, `update_last_used` |
| `update_last_used()` | 사용 | `authenticate_channel` |
| `list_channels()` | 사용 | cli/auth_cli.py |
| `authenticate_channel()` | 사용 | cli/collect.py |
| `register_channel()` | 사용 | cli/auth_cli.py |
| `revoke_channel()` | 사용 | cli/auth_cli.py |

### services/eqs.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `EQSService` | 사용 | cli/analyze.py |
| `EQSService.evaluate()` | 사용 | cli/analyze.py |

### services/forecaster.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `ForecasterService` | 사용 | cli/analyze.py |
| `ForecasterService.select_model()` | 사용 | 내부 (`predict`) |
| `ForecasterService.fill_missing_days()` | 사용 | 내부 (`predict`) |
| `ForecasterService.predict()` | 사용 | cli/analyze.py |
| `ForecasterService.detect_anomalies()` | 사용 | cli/analyze.py |

### services/llm_adapter.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `LLMAdapter` | 사용 | sentiment.py, topic_extractor.py |
| `LLMAdapter.complete()` | 사용 | 내부 (`complete_json`) |
| `LLMAdapter.complete_json()` | 사용 | eqs.py, segmenter.py, sentiment.py, topic_extractor.py |

### services/rate_limiter.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `RateLimiter` | 사용 | cli/collect.py, transcript.py, youtube_analytics.py |
| `RateLimiter.wait()` | 사용 | transcript.py, youtube_analytics.py |
| `RateLimiter.wait_on_error()` | 사용 | youtube_analytics.py |

### services/search_service.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `SearchService.load_config()` | 사용 | cli/search_cli.py |
| `SearchService.from_cli_flags()` | 사용 | cli/search_cli.py |
| `SearchService.search()` | 사용 | cli/search_cli.py |

### services/segmenter.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `SegmenterService` | 사용 | cli/analyze.py |
| `SegmenterService.segment_transcript()` | 사용 | cli/analyze.py |
| `compare_with_retention()` | **미사용** | 정의만 존재, 어디서도 호출하지 않음 |

### services/sentiment.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `SentimentService` | 사용 | cli/analyze.py |
| `SentimentService.analyze_batch()` | 사용 | cli/analyze.py |
| `cross_reference_questions_hotspots()` | **미사용** | 정의만 존재, topic_extractor.cross_reference_with_hotspots()가 대신 사용됨 |

### services/title_parser.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `SUPPLEMENTARY_KEYWORDS` | 내부 사용 | |
| `TitlePattern` | 내부 사용 | |
| `TitleParser` | **외부 사용 미확인** | cli에서 직접 호출 패턴 미발견 (아마 전 버전에서 사용) |
| `TitleParser.parse()` | 사용 | 내부 (`parse_batch`) |
| `TitleParser.parse_batch()` | 외부 사용 미확인 |
| `TitleParser.save_results()` | 외부 사용 미확인 |

**발견 [WARNING]**: TitleParser가 현재 CLI에서 직접 호출되는 `analyze parse-titles` 같은 커맨드가 없음. 다른 프로세스에서 사용될 수 있지만 CLI 파이프라인에 통합되지 않은 상태.

### services/topic_extractor.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `TopicExtractorService` | 사용 | cli/analyze.py |
| `TopicExtractorService.extract_topics()` | 사용 | cli/analyze.py |
| `TopicExtractorService.extract_questions()` | 사용 | cli/analyze.py |
| `TopicExtractorService.cross_reference_with_hotspots()` | 사용 | cli/analyze.py |

### services/transcript.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `TranscriptService` | 사용 | cli/collect.py |
| `TranscriptService.fetch_transcript()` | 사용 | cli/collect.py |

### services/validator.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `check_year_mismatch()` | 사용 | `run_all_validations` |
| `check_duplicates()` | 사용 | `run_all_validations` |
| `check_invalid_week()` | 사용 | `run_all_validations` |
| `check_name_inconsistency()` | 사용 | `run_all_validations` |
| `check_parse_failures()` | 사용 | `run_all_validations` |
| `check_session_gaps()` | 사용 | `run_all_validations` |
| `check_duration_outliers()` | 사용 | `run_all_validations` |
| `check_missing_weeks()` | 사용 | `run_all_validations` |
| `check_upload_gaps()` | 사용 | `run_all_validations` |
| `run_all_validations()` | 사용 | cli/validate_cli.py |
| `save_validation_results()` | 사용 | cli/validate_cli.py |
| `SEVERITY_ORDER` | 내부 사용 | |

### services/video_filter_service.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `VideoFilterService.filter_videos()` | 사용 | bundle_report.py, cli/report.py |
| `VideoFilterService.sort_videos()` | 사용 | bundle_report.py |

### services/youtube_analytics.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `YouTubeAnalyticsService` | 사용 | cli/collect.py |
| `.get_retention_data()` | 사용 | cli/collect.py |
| `.get_daily_metrics()` | 사용 | `collect_all_reports` |
| `.get_traffic_sources()` | 사용 | `collect_all_reports` |
| `.get_demographics()` | 사용 | `collect_all_reports` |
| `.get_geography()` | 사용 | `collect_all_reports` |
| `.get_devices()` | 사용 | `collect_all_reports` |
| `.get_playback_locations()` | 사용 | `collect_all_reports` |
| `.get_subscriber_changes()` | 사용 | `collect_all_reports` |
| `.get_engagement_metrics()` | **미사용** | `collect_all_reports`의 method_map에 포함되지 않음 |
| `.collect_all_reports()` | 사용 | cli/collect.py |
| `detect_rewatch_hotspots()` | 사용 | cli/analyze.py |
| `detect_skip_zones()` | 사용 | cli/analyze.py |

### services/youtube_data.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `YouTubeDataService` | 사용 | cli/collect.py |
| `.get_channel_info()` | 사용 | cli/collect.py |
| `.list_all_videos()` | 사용 | cli/collect.py |
| `.get_video_details()` | 사용 | cli/collect.py |
| `.filter_by_professor()` | 사용 | cli/collect.py |
| `.get_comments()` | 사용 | cli/collect.py |
| `.get_comment_replies()` | 사용 | 내부 (`get_comments`) |
| `.detect_new_videos()` | **미사용** | 정의만 존재, 호출자 없음 |

### services/youtube_reporting.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `YouTubeReportingService` | 사용 | cli/collect.py |
| `.list_report_types()` | 사용 | cli/collect.py |
| `.create_job()` | 사용 | cli/collect.py |
| `.get_job_status()` | 사용 | `poll_until_ready` |
| `.poll_until_ready()` | **미사용** | 정의만 존재 (CLI에서 non-blocking 패턴 사용) |
| `.download_report()` | **미사용** | CLI에서 download 단계 미구현 |
| `parse_report_csv()` | **미사용** | 모듈 내 정의만 존재 |

---

### storage/checkpoint.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `save_checkpoint()` | 사용 | cli/collect.py |
| `load_checkpoint()` | 사용 | cli/collect.py, cli/status.py |
| `is_stage_complete()` | **미사용** | 정의만 존재, 호출자 없음 |
| `mark_stage_complete()` | **미사용** | 정의만 존재, 호출자 없음 |
| `clear_checkpoint()` | **미사용** | 정의만 존재, 호출자 없음 |

**발견 [INFO]**: `is_stage_complete`, `mark_stage_complete`, `clear_checkpoint`가 구현되어 있지만 CLI에서 사용하지 않음. `collect_all` 파이프라인에서 스테이지 스킵/재개에 활용할 수 있으나 현재 미통합.

### storage/json_store.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `read_json()` | 사용 | 다수 (checkpoint, cli/*, reporting/*) |
| `write_json()` | 사용 | 다수 (checkpoint, cli/*, reporting/*) |

### storage/parquet_store.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `read_parquet()` | 사용 | cli/analyze.py |
| `write_parquet()` | 사용 | cli/collect.py, cli/analyze.py |
| `append_parquet()` | **미사용** | 정의만 존재 |

---

### reporting/bundle_report.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `BundleReportGenerator` | 사용 | cli/report.py |
| `.generate()` | 사용 | cli/report.py |
| `.render_pdf()` | 사용 | cli/report.py |
| `.generate_from_html()` | 사용 | cli/report.py |

### reporting/channel_report.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `ImprovementSuggestion` | 사용 | 내부 |
| `compare_videos()` | 사용 | 내부 (`generate_improvement_suggestions`, `generate`) |
| `generate_improvement_suggestions()` | 사용 | `ChannelReportGenerator.generate()` |
| `ChannelReportGenerator` | 사용 | cli/report.py |
| `.generate()` | 사용 | cli/report.py |

### reporting/comment_report.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `CommentReportGenerator` | 사용 | cli/report.py |
| `.generate()` | 사용 | cli/report.py |

### reporting/department_report.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `DepartmentReportGenerator` | 사용 | cli/report.py |
| `.compute_overview()` | 사용 | cli/report.py |
| `.compute_professor_details()` | 사용 | cli/report.py |
| `.compute_compliance()` | 사용 | cli/report.py |
| `.generate_html()` | 사용 | cli/report.py |
| `.generate_pdf()` | 사용 | cli/report.py |

### reporting/excel_export.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `ExcelExporter` | 사용 | cli/report.py |
| `.export()` | 사용 | cli/report.py |

### reporting/notebook_export.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `VideoNotebookExporter` | 사용 | cli/report.py |
| `.export()` | 사용 | cli/report.py |

### reporting/video_report.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `VideoReportGenerator` | 사용 | cli/report.py |
| `.generate()` | 사용 | cli/report.py |
| `generate_suggestions()` | 사용 | `VideoReportGenerator.generate()` |

---

### visualization/charts.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `create_retention_chart()` | **미사용** | 어디서도 호출하지 않음 (cli에 retention chart 생성 단계 없음) |
| `create_trend_chart_html()` | 사용 | reporting/channel_report.py |

**발견 [INFO]**: `create_retention_chart()`가 정의만 존재. analyze retention이 JSON만 저장하고, chart 생성은 호출하지 않음.

---

### output/manager.py

| Public API | 사용 여부 | 호출자 |
|-----------|----------|-------|
| `ProjectManager` | 사용 | cli/project.py |
| `OutputManager` | 사용 | cli/search_cli.py, cli/validate_cli.py |

---

### cli/ (10 모듈)

모든 CLI 명령 함수는 `cli/main.py`에서 등록되어 사용됨. 특별한 미사용 API 없음.

---

## B. 계약 불일치 목록

### 1. 반환 타입 불일치

| 위치 | 함수명 | 문제 설명 |
|------|--------|---------|
| `services/youtube_analytics.py` | `get_daily_metrics()` 등 8개 메서드 | Pydantic 모델 (`DailyMetrics` 등)이 정의되어 있지만 서비스가 `list[dict]` 반환. 모델과 서비스 계약 불일치. |
| `services/eqs.py:62-104` | `EQSService.evaluate()` | 반환 타입이 `dict[str, Any]`로 선언되었지만, 빈 transcript일 때와 정상 처리 시 dict 구조가 다름 (빈 경우 video_id 포함, LLM 경우도 video_id 포함 — 이 경우는 일관됨). **실제 불일치 없음, 구조 일관.** |
| `models/video.py:104-114` | `Forecast` | `date` 필드가 `Any` 타입으로 선언됨. 직렬화/역직렬화 시 타입 정보 손실 위험. |
| `services/forecaster.py` | `predict()`, `detect_anomalies()` | Forecast Pydantic 모델이 존재하지만 dict 반환. 모델 미사용. |

### 2. 미처리 예외

| raise 위치 | 예외 타입 | 호출자에서 except 여부 |
|-----------|----------|---------------------|
| `services/llm_adapter.py:149` | `ValueError` ("Failed to parse LLM response") | eqs.py, segmenter.py에서 미처리. CLI까지 전파 시 `analyze eqs`/`analyze transcript`에서 catch되지만 generic `Exception`으로만. |
| `services/rate_limiter.py:58` | `RuntimeError` ("Max retries exceeded") | youtube_analytics.py `_query`에서 미처리 — `wait_on_error()` 호출 후 `RuntimeError` 발생 시 상위로 전파. CLI의 generic except에서 잡힘. |
| `services/forecaster.py:109` | `ValueError` ("At least 6 months") | cli/analyze.py:688에서 `ValueError`로 적절히 처리됨. |
| `services/youtube_analytics.py:105` | `PermissionError` | cli/collect.py:714에서 적절히 처리됨. |
| `services/auth.py:258` | `ValueError` ("Token cannot be refreshed") | cli/collect.py:100에서 `ValueError`로 적절히 처리됨. |

**주요 발견 [WARNING]**: `RateLimiter.wait_on_error()` → `RuntimeError`가 `YouTubeAnalyticsService._query()`에서 호출되지만, `_query` 루프가 `attempt < max_retries - 1`까지만 호출하므로 실제로는 `RuntimeError`가 발생하지 않음. 그러나 `wait_on_error()`를 직접 호출하는 코드에서는 주의 필요.

### 3. Pydantic 직렬화 문제

| 모델 | 필드 | 문제 |
|------|------|------|
| `Forecast` (video.py:109) | `date: Any` | 타입이 `Any`로 선언됨. `model_dump()` → `model_validate()` 왕복 시 date 객체가 문자열로 변환될 수 있음. |
| `CollectionState` (config.py:151) | `started_at: datetime \| None`, `updated_at: datetime \| None` | `model_dump(mode="json")` 사용 시 datetime이 ISO 문자열로 변환. `checkpoint.py`에서 `CollectionState(**state_data)` 역직렬화 시 문자열 → datetime 변환은 Pydantic v2가 자동 처리하므로 **정상 동작**. |
| `ChannelRegistration` (config.py:220) | `registered_at: str`, `last_used_at: str` | datetime이 아닌 str로 선언되어 있어 형식 검증 없음. 잘못된 문자열이 들어갈 수 있음. |
| `CalendarEvent` (config.py:168) | `start_date: str`, `end_date: str` | ISO date 형식이 요구되지만 str 타입이므로 "abc" 같은 값도 통과. `end_date_must_be_gte_start_date` validator가 문자열 비교만 수행. |

### 4. Optional 전파 미처리

| 위치 | 체인 | 문제 |
|------|------|------|
| `reporting/department_report.py:100-108` | `video_map[pt.video_id]` | `filtered_parsed`에 있는 video_id가 `filtered_videos`에 없을 수 있음 (데이터 불일치 시). `if pt.video_id in video_map` 가드가 있으므로 **안전**. |
| `services/youtube_analytics.py:88-92` | `self._rate_limiter.profile.max_retries` | rate_limiter가 None일 때 fallback 있음 (`_MAX_RETRIES`). **안전**. |
| `cli/report.py:282-284` | `gen._load_video_meta()` → `gen._load_retention()` | 둘 다 None 가능 반환이지만 template에서 None 처리됨. **안전**. |

---

## C. 패키지별 상세

### models/ — Pydantic 직렬화, 필드 기본값, validator 로직

**직렬화 왕복 검증**:
- `AnalyticsReport`, `DailyMetrics`, `TrafficSource` 등: 왕복 가능하지만 **사용되지 않음**.
- `CollectionState`: `model_dump(mode="json")` → `CollectionState(**data)` 왕복 정상 (Pydantic v2 자동 datetime 파싱).
- `Forecast.date: Any`: **왕복 실패 위험**. date 객체 → JSON → 역직렬화 시 문자열로 남을 수 있음.
- `ChannelRegistration.registered_at: str`: 형식 검증 없음, 그러나 항상 `datetime.now(UTC).isoformat()`로 설정되므로 실질적 위험 낮음.

**Validator 로직**:
- `channel_id_must_start_with_uc` 패턴이 3곳에서 중복 정의 (analytics.py, channel.py, config.py). 일관성은 유지되지만 DRY 원칙 위반.
- `CalendarEvent.end_date_must_be_gte_start_date`: 문자열 비교로 구현. ISO date 형식이 보장되면 정상 동작하지만, 형식이 다를 경우 오류 발생하지 않고 잘못된 결과.

### services/ — API 호출 → 모델 변환, 에러 래핑, rate limit 적용

**API 호출 → 모델 변환 [WARNING]**:
- `YouTubeAnalyticsService`: 8개 메서드 모두 plain dict 반환. 대응 Pydantic 모델이 models/analytics.py에 존재하지만 사용하지 않음. **타입 안전성 계약 깨짐**.
- `YouTubeDataService.get_channel_info()`: dict 반환 → `Channel` 모델 사용하지 않음.
- `EQSService.evaluate()`: dict 반환 → `QualityScore` 모델 사용하지 않음.
- `ForecasterService.predict()`: dict 반환 → `Forecast` 모델 사용하지 않음.

**에러 래핑**:
- `YouTubeAnalyticsService._query()`: HttpError → PermissionError 래핑 적절.
- `YouTubeReportingService.create_job()`: HttpError → PermissionError/RuntimeError 래핑 적절.
- `YouTubeDataService.get_comments()`: HttpError 403/404 → 빈 리스트 반환 (silent). 로깅은 있음.

**Rate limit 적용 여부**:
- `TranscriptService`: rate_limiter 적용됨 (wait 호출).
- `YouTubeAnalyticsService`: rate_limiter 적용됨 (_query에서 wait + wait_on_error).
- `YouTubeDataService`: **rate_limiter 미적용**. `list_all_videos()`, `get_video_details()`, `get_comments()` 모두 rate limiting 없이 API 호출. 대량 요청 시 quota 소진 위험.
- `YouTubeReportingService`: rate_limiter 미적용 (단일 요청이므로 위험 낮음).

### storage/ — atomic write 보장, 체크포인트 무결성

**Atomic write**:
- `json_store.write_json()`: temp file + rename 패턴으로 atomic write 보장. **정상**.
- `parquet_store.write_parquet()`: 직접 `df.write_parquet()` 호출. **비원자적**. 쓰기 중 크래시 시 파일 손상 가능.
- `parquet_store.append_parquet()`: read + concat + write 패턴. 비원자적이며 동시 접근 시 데이터 손실 가능.

**체크포인트 무결성**:
- `checkpoint.save_checkpoint()`: `write_json()`을 사용하므로 atomic write 보장.
- `checkpoint.load_checkpoint()`: None 반환 시 호출자가 적절히 처리.

### reporting/ — 빈 데이터 입력 시 동작, 템플릿 변수 누락

**빈 데이터 입력**:
- `BundleReportGenerator.generate()`: `filtered` 비어있으면 `ValueError` raise. **적절**.
- `ChannelReportGenerator.generate()`: 빈 videos → `_generate_insights()` → `["No videos to analyze."]`. 정상.
- `DepartmentReportGenerator`: 빈 parsed_titles → 빈 리스트/0값 반환. 정상.
- `CommentReportGenerator`: topics 빈 리스트 → 템플릿에서 빈 상태 렌더링. 정상.

**템플릿 변수 누락 가능성**:
- `bundle_report.html` 템플릿이 `title`, `channel_id`, `filter_description`, `videos`, `summary`, `generated_at`를 요구. 모두 `generate()`에서 전달됨.
- `channel_report.html`이 `trend_chart_html` 변수를 사용하는데, daily_data가 없으면 빈 문자열 전달. Jinja2에서 빈 문자열은 falsy이므로 `{% if trend_chart_html %}` 조건부 렌더링 가능.

### cli/ — typer 옵션 → 서비스 호출 매핑, exit code 일관성

**Internal API 외부 호출 [WARNING]**:
- `cli/report.py:282`: `gen._load_video_meta(video_id, channel_id)` — private 메서드 호출.
- `cli/report.py:283`: `gen._load_retention(video_id)` — private 메서드 호출.
- `cli/report.py:284`: `gen._load_segments(video_id)` — private 메서드 호출.
- `cli/report.py:663`: `gen._load_videos_meta(channel_id)` — private 메서드 호출.

이들은 `VideoReportGenerator`와 `BundleReportGenerator`의 `_` prefix 메서드를 CLI에서 직접 호출. notebook export 경로에서 데이터를 로드하기 위해 필요하지만, public API로 노출하거나 별도 로더를 만들어야 함.

**Exit code 일관성**:
| Exit Code | 의미 | 사용 위치 |
|-----------|------|----------|
| 0 | 성공 | (기본) |
| 1 | 일반 오류 | 대부분의 명령 |
| 2 | Quota 초과 / 특수 오류 | collect videos, collect analytics, auth register |
| 3 | API 오류 | collect analytics |

`auth_cli._revoke_channel` exit(1), `auth_cli._register_channel` exit(1) FileNotFoundError / exit(2) ValueError — 의미가 collect과 다름.

**typer 옵션 매핑**:
- `collect_all_command`: 내부에서 각 stage 함수를 직접 호출할 때 `kwargs`로 명시적 기본값을 전달. Typer OptionInfo 문제를 올바르게 우회.
- `analyze_all_command`: lambda 래핑으로 각 분석 함수 호출. SystemExit을 pass로 무시 — 개별 단계 실패 시 다음 단계 진행 가능.

---

## 종합 주요 발견사항

### CRITICAL (0건)
없음.

### WARNING (5건)

1. **W-L2-001**: models/analytics.py의 7개 Pydantic 모델(`DailyMetrics` 등)이 정의만 있고, 서비스가 plain dict 반환. 모델-서비스 계약 불일치.
2. **W-L2-002**: models/video.py의 `ViewingPattern`, `TranscriptSegment`, `QualityScore`, `Forecast` 모델이 미사용. 서비스가 dict 반환.
3. **W-L2-003**: `cli/report.py`에서 `VideoReportGenerator`/`BundleReportGenerator`의 `_` prefix 메서드 4곳 직접 호출. 내부 API 캡슐화 위반.
4. **W-L2-004**: `YouTubeDataService`에 rate limiter 미적용. 대량 API 호출 시 quota 소진 위험.
5. **W-L2-005**: `Forecast.date` 필드가 `Any` 타입. 직렬화 왕복 시 타입 정보 손실.

### INFO (7건)

1. **I-L2-001**: models/comment.py `Comment` 모델 미사용.
2. **I-L2-002**: models/channel.py `Channel` 모델 미사용.
3. **I-L2-003**: models/config.py `PipelineResult`, `Report` 모델 미사용.
4. **I-L2-004**: services/segmenter.py `compare_with_retention()` 미사용.
5. **I-L2-005**: services/sentiment.py `cross_reference_questions_hotspots()` 미사용.
6. **I-L2-006**: storage/checkpoint.py `is_stage_complete()`, `mark_stage_complete()`, `clear_checkpoint()` 미사용.
7. **I-L2-007**: storage/parquet_store.py `append_parquet()`, visualization/charts.py `create_retention_chart()`, services/youtube_data.py `detect_new_videos()`, services/youtube_reporting.py `poll_until_ready()`, `download_report()`, `parse_report_csv()`, services/youtube_analytics.py `get_engagement_metrics()` — 총 7개 함수 미사용.
