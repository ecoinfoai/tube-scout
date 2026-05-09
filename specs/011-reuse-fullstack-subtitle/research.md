# Phase 0 Research: Subtitle Full-Stack Reuse Detection

**Feature**: 011-reuse-fullstack-subtitle
**Created**: 2026-05-09
**Status**: Complete — all clarifications resolved in spec.md `## Clarifications` (Session 2026-05-09); Technical Context contains zero `NEEDS CLARIFICATION` markers.

본 문서는 plan.md Technical Context에서 명시되지 않은 알고리즘·운영 결정의 근거를 정리한다. 의존성 surface는 spec 007 인계 그대로이며 신규 패키지 0개이므로, 의사결정은 (a) 알고리즘 선택, (b) 영속 스키마 진화 전략, (c) 운영 시간 budget 분배에 집중된다.

---

## R-1. nC2 caption pool 크기 폭증 대응 — Layer A 사전 필터의 위치

**Decision**: Layer A 길이 필터를 시간축 지표 계산 전에 두고, I-2 cosine만으로 1차 cull 후 후보 쌍에 대해서만 segment alignment 수행.

**Rationale**:
- 200 영상 → 19,900 쌍. 모든 쌍에 대해 segment alignment를 수행하면 SC-001 (30분) 예산을 초과한다.
- 임베딩은 spec 007이 이미 산출한 video-level embedding을 재사용해 cosine을 O(N²) 행렬 연산 1회로 빠르게 계산 가능 (200×200 = 40k 연산, <1초).
- 1차 cull 임계는 보수적 (예: cosine ≥ 0.55) 으로 두고, 통과한 쌍만 segment alignment + I-6/I-7/I-8 + Layer A 길이 컷을 수행. 이렇게 하면 계산 부담이 의심 후보 비율(경험적으로 5–15%)에 비례.
- Layer A 길이 컷은 I-6 산출 후에야 정확하게 적용 가능하므로, "사전 필터(I-2 cosine 기반 cheap cull) → 정밀 필터(I-6 길이 기반)"의 2단계 구성.

**Alternatives considered**:
- (a) 모든 쌍에 segment alignment: 정확하지만 19,900 × 평균 alignment 비용으로 30분 예산 초과.
- (b) Layer A를 cosine 단계로 옮기기: 길이 정보가 없어 즉흥 5분 일치를 cosine으로 잡지 못해 false negative 위험.
- (c) Approximate nearest neighbor (ANN) 인덱스: 200 영상 규모에서는 brute-force matrix가 더 빠름. 장기 4,000 영상도 16M 연산으로 충분히 단일 노드 처리 가능. 추가 의존성(faiss/annoy) 도입은 Constitution V violation 위험.

**Implementation note**: `services/nc2_matcher.py` 가 1차 cosine cull → 후보 쌍 리스트 반환. `services/time_axis_indicators.py` 가 후보 쌍에 대해서만 alignment + I-6/I-7/I-8 산출.

---

## R-2. Segment alignment 알고리즘 — 동일 자막 구간 검출

**Decision**: Sentence-level normalized exact match + greedy left-to-right span extension.

**Rationale**:
- 자막은 timestamp + text segment 리스트로 spec 007 transcript JSON에 저장되어 있다.
- 두 영상의 segment를 normalized text(공백·구두점·case·full/half-width)로 비교, 동일한 segment를 anchor로 잡고 좌우로 확장해 가장 긴 일치 구간을 찾는다 (lecture 자막은 단조 시퀀스, swap이 드물어 LCS의 sequence ordering 이점이 거의 없음).
- 평균 자막 길이 60분 → segment 약 600개. greedy LCS-like는 O(N×M) ≈ 360k 연산/쌍, 1차 후보 (수백 쌍)에 대해 충분히 빠름.

**Alternatives considered**:
- (a) Suffix array / suffix automaton: O((N+M) log(N+M)) 구축 비용이 있지만 lecture 자막 규모에서는 greedy 대비 이득 미미.
- (b) Dynamic time warping (DTW): 속도 변화 대응에 강하지만 PS-A-4 (1.5배속) 케이스는 v0.8 spec으로 미룸. v0.4 scope OUT.
- (c) Embedding-level segment alignment: 노이즈에 강하지만 false positive (의미 비슷하나 본문 다름) 가 늘어 SC-007 (90% 인간 일치) 충돌. M-default 정합성 위해 normalized exact가 안전.

**Implementation note**: `services/time_axis_indicators.py::find_match_spans(segments_a, segments_b) -> list[MatchSpan]` 가 기본 단위. MatchSpan은 (start_a, end_a, start_b, end_b, length_seconds) 5-tuple. I-6 = max length, I-7 = stdev of lengths (or count of distinct clusters), I-8 = positional spread (early/middle/late thirds).

---

## R-3. Layer B baseline corpus 표현 — phrase 단위 vs n-gram 단위

**Decision**: Phrase-level (sentence-grain) 으로 baseline 등록. n-gram 인덱싱은 v0.4 도입 안 함.

**Rationale**:
- baseline 의도는 "교수의 반복 어법 흡수" — 운영자가 명시적으로 마킹할 단위는 자연스러운 발화 단위(문장).
- ASR segment 경계가 발화 단위와 거의 일치하므로 phrase = segment text가 자연스럽다.
- n-gram 기반은 통계적으로 정확할 수 있으나 운영자가 "왜 이게 차감됐지?" 를 audit 하기 어렵다. SC-008 (감춤 0건) 정신과 충돌.
- bootstrap 임계: 한 교수의 가장 이른 5 영상 중 ≥3 영상에 동일 normalized phrase가 등장하면 baseline 시드 (FR-012). 이후 운영자가 mark 하면 즉시 추가.

**Alternatives considered**:
- n-gram TF-IDF baseline: 정확하나 audit 어렵고 storage 무거움.
- 자동 비교 후 phrase 추천만: 첫 분석에서 baseline 미작동 → SC-004 미달 위험. 운영 1주차에 대량 false positive 누적.

**Implementation note**: `services/baseline_corpus.py::bootstrap(professor_id, earliest_videos)` 와 `add_phrase(professor_id, phrase, source_video_id, admin)` 두 함수. 영속 테이블 `baseline_corpus(professor_id, phrase_normalized, raw_phrase, occurrences, registered_at, registered_by)`.

---

## R-4. Layer C 점진 진화 등급 컷 — 임계 결정 시점

**Decision**: v0.4 launch에서는 spec.md Assumptions에 명시된 default (60–75% I-2 → demote to moderate) 로 시작하고, 운영 2–4주 동안 admin이 FALSE_POSITIVE 패턴을 검토한 결과를 토대로 정책 문서(idea/idea-2026-05-09-roadmap.md §7.4)에서 calibrate.

**Rationale**:
- 운영자 합의가 spec 011 작업 전 정책 문서로 명시되어 있으나, 정책 문서가 늦어도 launch는 진행할 수 있어야 한다 (4–6주 dev-squad 일정 보호).
- 기본값을 conservative recall 쪽으로 두면 false negative 회피 + 운영자가 demoted된 쌍을 검토에서 끌어올릴 수 있음.
- FR-027이 모든 정책 임계를 project-level config로 두므로 calibration 시점에 코드 수정 0건.

**Alternatives considered**:
- 정책 문서 완성 전 dev 차단: 실효적 4–6주 추가 지연.
- 기본값 critical 쪽으로 보수: 누락된 진짜 재활용을 검토자가 보지 못함 → SC-007 미달.

**Implementation note**: Project policy 파일(`02_analyze/content/policy.yaml`) 에 다음 키 — `layer_a_min_seconds: 60`, `layer_c_evolution_band: [0.60, 0.75]`, `composite_weights: {i1:..., i2:..., ..., i6:..., i7:..., i8:...}`. `services/layer_defense.py` 가 이 파일을 1회 로딩.

---

## R-5. Per-pair checkpoint 표현 — 별도 테이블 vs comparison_results 활용

**Decision**: `comparison_results` 테이블의 자체 row 존재 여부를 checkpoint로 사용 + 별도 `pair_checkpoint(run_id, pair_count_total, pair_count_done, last_pair_at)` 메타 테이블로 진행률 표시.

**Rationale**:
- `comparison_results` 는 idempotent UPSERT 가능 — 한 쌍에 대한 결과가 이미 있으면 스킵, 없으면 산출 후 INSERT.
- 별도 checkpoint 테이블에 진행 메트릭만 저장하면 UI/CLI가 "x / y 쌍 완료" 표시 가능.
- 중단 후 재시작 시 단순 재실행만으로 미완료 쌍부터 재개 (FR-031).

**Alternatives considered**:
- (a) per-pair JSON checkpoint files: 19,900 쌍 → 19,900 파일. 파일시스템 오버헤드 + 원자적 갱신 어려움.
- (b) WAL-only: 운영자가 진행률 모니터링 못함.

**Implementation note**: `services/pair_checkpoint.py::iterate_unfinished_pairs(pool, db)` generator, 매 yield 마다 `comparison_results` 조회 후 미존재 쌍만 반환. 완료 시 `pair_checkpoint` 메타 row 갱신.

---

## R-6. Concurrent admin write — fcntl advisory lock vs SQLite BEGIN IMMEDIATE

**Decision**: SQLite `BEGIN IMMEDIATE` 트랜잭션 + retry 0회 정책 (즉시 실패) + admin user-facing 명시 메시지.

**Rationale**:
- SQLite는 `BEGIN IMMEDIATE` 가 lock 획득 실패 시 즉시 `SQLITE_BUSY` 반환. 두 번째 admin write가 진행 중이면 명확하게 거부 (FR-033).
- 추가 fcntl flock 도입은 cross-platform 복잡성 증가 + 본 spec 운영 환경(Linux 단일 노드)에서 SQLite lock으로 충분.
- spec 009가 이미 token 파일에 fcntl flock을 도입했으나, content_reuse.db는 SQLite 자체 락이 1차 보호.

**Alternatives considered**:
- (a) Optimistic concurrency with version field: spec.md Q5가 거부.
- (b) Retry with backoff: silent serialization 가능. user 의 "다른 admin이 동시 작업 중" 인지를 사용자에게 보이지 않음.
- (c) File-level fcntl flock: cross-platform 까다로움 + SQLite와 이중 락.

**Implementation note**: `services/advisory_lock.py::layer_d_write_lock(db_path)` context manager. `BEGIN IMMEDIATE` 시도, `OperationalError("database is locked")` 발생 시 영문 메시지로 변환: `"Another administrator is currently writing to the review state. Please retry in a moment."` 반환 → CLI에서는 non-zero exit, web UI(spec 014)는 409 Conflict.

---

## R-7. Phrase normalization 알고리즘 — Q3 결정 구체화

**Decision**: 다음 순서로 normalize 후 exact 비교.

1. Unicode NFKC normalization (전각 → 반각, 호환 글리프 통일).
2. Lowercase (English letters; 한글은 case 영향 없음).
3. Punctuation strip — 한글·영문 punctuation set (`。、，．・「」『』""''‥…—–-,.!?;:()[]{}`) 모두 제거.
4. Whitespace collapse — 다중 whitespace를 single ASCII space로, 양 끝 trim.
5. 결과 문자열 exact equality check.

**Rationale**:
- ASR 자막은 동일 발화에서도 공백·구두점이 일관되지 않다.
- NFKC는 전각/반각 한자·기호 통일에 표준.
- 의미 동등성 (예: "안녕하세요" ≈ "안녕하시지요") 까지는 normalize 하지 않음 — fuzzy로 흐르면 SC-005 (재알림 0건) 검증이 모호해짐.

**Alternatives considered**:
- 형태소 분석 후 비교: KoNLPy 의존성 도입 비용 + accuracy 미보장.
- Case-sensitive raw exact: ASR 변동에 너무 취약.

**Implementation note**: `services/phrase_whitelist.py::normalize_phrase(text: str) -> str` 단일 함수, 위 5 단계. 모든 phrase 영속 시 normalized + raw 둘 다 저장 (audit + display 위해).

---

## R-8. Cross-channel professor 통합 — Q4 매핑 자료구조

**Decision**: 신규 SQLite 테이블 `professor_pool(professor_id, channel_alias, author_marker, display_name, registered_at, registered_by)` + CLI 명령 `tube-scout content professor map --alias <a> --author <name> --professor-id <id>`.

**Rationale**:
- spec 003가 channel_alias → channel_id를 보관하지만 한 채널 내 다교수 환경(학과 메인 채널)에서 author 식별이 별도로 필요.
- author_marker는 video metadata의 (a) 채널 게시자 기본명 + (b) parsed_titles의 교수 필드 둘 중 하나를 운영자가 선택해 매핑.
- mapping 부재 시 fallback: 채널-단위 풀 (FR-032 후반부 요구사항).
- 운영자가 명시적으로 등록하기 전까지는 같은 video가 여러 풀에 중복 노출되지 않음.

**Alternatives considered**:
- 자동 추출 (이름 매칭): 동명이인 위험 + 운영자 통제 부재.
- 별칭 기반 통합 (channel_alias 자체에 교수 1인 가정): 학과 메인 채널 사용 불가능.

**Implementation note**: `services/professor_resolver.py::resolve_professor_pool(professor_id, channels_registry, db) -> list[VideoRef]` — 매핑된 (alias, author) 모음에서 video 리스트 통합. 매핑 없으면 ValueError + 영문 메시지.

---

## R-9. 4 패턴 분류 임계 — whole vs scattered, same-week vs diff-week

**Decision**:
- `whole` ↔ `scattered`: I-6(최장 연속 일치) ≥ 0.5 × min(duration_a, duration_b) 이고 I-7(분포) <= median × 1.5 이면 `whole`. 그 외 `scattered`.
- `same-week` ↔ `diff-week`: spec 007 parsed_titles 의 week_number 동일이면 `same-week`. parse_error 또는 missing이면 `diff-week`로 fallback.

**Rationale**:
- 운영자 시나리오 PS-U-3a (20분 통째 ≈ 50% 영상 ≈ 100% 한쪽) 와 PS-U-3b (5분×4, 즉 4 분산) 를 명확히 분리하려면 "절반 이상 연속 + 분포 좁음" 이 강한 시그널.
- 50% 임계는 conservative — "20분 / 40분" 케이스를 whole 로 잡고 "10분 / 90분" 케이스는 scattered 로 분류 (운영자 의도와 부합).
- 임계는 FR-027 정책 config로 노출하여 calibration 가능.

**Alternatives considered**:
- 단순 I-6 ≥ 600초 절대 임계: 40분 영상 vs 90분 영상 비교에서 일관 부족.
- 동일 비율(예: 30%) 만으로: 다양한 영상 길이에서 의도와 어긋나는 경계.

**Implementation note**: `services/pattern_classifier.py::classify(comparison_result) -> ReusePatternLabel`. config에서 thresholds 로딩.

---

## R-10. 영속 schema migration — spec 007 → spec 011

**Decision**: SQLite `ALTER TABLE comparison_results ADD COLUMN ...` (idempotent, IF NOT EXISTS via PRAGMA + sqlite_master 조회) + 신규 테이블 `CREATE TABLE IF NOT EXISTS`. 기존 데이터는 모두 보존되며 신규 컬럼은 NULL 허용 (구 분석 결과는 시간축 지표 비어 있음 — 보고서에서 "spec 007 analysis" 라벨로 구분).

**Rationale**:
- SC-009 (backward 호환) 충족 — 기존 분석 결과 재사용.
- ALTER TABLE 은 SQLite에서 idempotent하지 않으나 sqlite_master + PRAGMA table_info 로 컬럼 존재 여부 사전 확인하여 동등 효과 달성.
- 신규 컬럼 NULL 허용으로 spec 007 row 들에 영향 없음.

**Alternatives considered**:
- 신규 DB 파일: backward 호환을 깨고 운영자에게 migration 부담.
- 기존 row 재계산: 자막 풀 변동 가능성으로 운영 트리거에 위임이 안전.

**Implementation note**: `storage/content_db.py::migrate_to_v2(db_path)` — 1회 실행, 기존 컬럼/테이블 존재 여부 확인 후 부족분만 추가. CLI startup에서 자동 호출.

---

## 결론

모든 NEEDS CLARIFICATION 0건. spec 007 의존성(SQLite, sentence-transformers, polars, jinja2) 그대로 + 신규 의존성 0개. 2단계 매칭(cosine cull → segment alignment), per-pair checkpoint via comparison_results idempotency, fcntl-free SQLite BEGIN IMMEDIATE 락, 5단계 phrase normalization 이 본 spec의 알고리즘 spine. 정책 임계는 모두 project config로 이동시켜 launch 후 calibration 가능. Phase 1 design 진행 가능.
