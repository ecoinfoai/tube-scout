# Layer 4: E2E Pipeline Audit Results

## 요약
| 시나리오 | 테스트 수 | PASS | FAIL |
|---------|----------|------|------|
| E2E-1 신규 전체 수집 | 2 | 2 | 0 |
| E2E-2 학과 보고서 | 2 | 2 | 0 |
| E2E-3 번들 보고서 | 2 | 2 | 0 |
| E2E-4 제목 검증 | 1 | 1 | 0 |
| E2E-5 중단 복구 | 3 | 3 | 0 |
| E2E-6 멀티채널 | 2 | 2 | 0 |
| 데이터 정합성 | 2 | 2 | 0 |
| **합계** | **14** | **14** | **0** |

## FAIL 상세
없음 (전체 PASS)

## 데이터 정합성 검증 결과

| 검증 항목 | 결과 | 비고 |
|----------|------|------|
| video_id 집합 일치 (JSON = Parquet) | PASS | `test_json_parquet_video_id_consistency` |
| video_id 집합 일치 (collect = parsed) | PASS | `test_department_report_video_id_consistency` |
| Pydantic 역직렬화 100% | PASS | `test_collected_data_pydantic_roundtrip` — Video 모델 |
| CollectionState 역직렬화 | PASS | `test_checkpoint_state_model_roundtrip` |
| 번들 보고서 필터 정합성 | PASS | `test_bundle_report_with_keyword_filter` — 필터된 영상만 포함 확인 |

## 발견 사항 (코드 이슈, 테스트 실패는 아님)

1. **체크포인트 경로 이중 중첩**: `_checkpoint_path(data_dir)` 가 `data_dir / "checkpoints" / "collection_state.json"` 을 반환하는데, `mgr.checkpoint_dir` 자체가 이미 `…/checkpoints/` 이므로 실제 파일 경로가 `…/checkpoints/checkpoints/collection_state.json` 으로 이중 중첩됨. 동작에는 문제 없으나 경로가 비직관적. (WARNING)

## PASS 요약

- **E2E-1**: `init` -> `collect all` 전체 파이프라인 정상. config.json 생성, professor 필터링 (3->2 videos), Parquet 병행 저장, 체크포인트 기록 모두 확인.
- **E2E-2**: `collect videos` -> `report department --format xlsx` 성공. Excel 파일 생성, 2+ 시트 구성 확인. parsed title video_ids = collected video_ids 일치.
- **E2E-3**: `report bundle --keyword "Lecture 1"` 에서 필터 정확성 확인. HTML에 "Lecture 1"만 포함, "Lecture 2" 미포함. `--video-ids` 필터도 정상.
- **E2E-4**: 의도적 V-001 (연도 불일치), V-002 (중복), V-003 (주차 초과), V-005 (파싱 실패) 트리거 데이터로 `run_all_validations` 호출 시 4개 규칙 모두 탐지 확인.
- **E2E-5**: 체크포인트 기반 resume 정상 — 완료된 단계 재실행 시 "already collected" 스킵, `--force-refresh` 시 재수집, API 에러 시 "interrupted" 체크포인트 저장.
- **E2E-6**: 두 채널의 데이터 완전 격리 확인. 프로젝트 디렉터리, video_ids, 체크포인트 모두 독립.
- **데이터 정합성**: JSON/Parquet video_id 일치, Pydantic 모델 역직렬화 100%, 체크포인트 상태 모델 roundtrip 성공.
