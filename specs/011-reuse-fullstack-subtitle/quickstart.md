# Quickstart: Subtitle Full-Stack Reuse Detection (spec 011)

**Feature**: 011-reuse-fullstack-subtitle
**Audience**: 운영자(DX센터장) — 출시된 v0.4 빌드를 처음 실행할 때 따라가는 흐름.
**Pre-condition**: spec 007 + spec 010 빌드가 이미 작동 중이고, 대상 채널의 자막 수집이 끝나 있음.

본 문서는 spec 011 기능을 1회 실제 데이터로 검증할 수 있는 최소 시나리오를 제공한다. 동시에 acceptance 테스트(`tests/integration/test_nc2_pipeline.py` 등) 의 narrative reference 역할을 한다.

---

## 0. 가정 환경

- Project directory: `~/projects/2026-05-09-park-jc-nc2/` (예시)
- 자막 수집 완료: `01_collect/transcripts/{video_id}.json` 충분히 존재
- spec 007 분석이 이미 1회 실행되어 `02_analyze/content/content_reuse.db`, `embeddings.parquet` 존재
- 같은 교수 (예: `prof-park-jc`) 의 영상이 두 개 채널에 분산: 학과 메인 채널 (`alias=nursing`) + 본인 개인 채널 (`alias=park-personal`)

---

## 1. Migration (스키마 v2 적용)

```bash
# CLI 시작 시 자동 호출되지만, 수동 검증 가능
tube-scout content policy show --project ~/projects/2026-05-09-park-jc-nc2/
```

처음 실행 시 자동 migration이 작동하고 `_schema_version` 테이블에 `spec-011 / v1` 가 기록된다. 이후 호출은 idempotent.

**검증 쿼리**:

```bash
sqlite3 ~/projects/2026-05-09-park-jc-nc2/02_analyze/content/content_reuse.db \
  "SELECT spec, version, applied_at FROM _schema_version;"
```

기대 결과: `spec-011 | v1 | 2026-05-09T...`.

---

## 2. 정책 YAML 작성

```bash
# 템플릿 확인 (read-only)
tube-scout content policy show --project ~/projects/2026-05-09-park-jc-nc2/

# 직접 작성/수정 (텍스트 에디터)
$EDITOR ~/projects/2026-05-09-park-jc-nc2/02_analyze/content/policy.yaml
```

처음 launch 시는 spec 011 default(`layer_a_min_seconds=60`, `layer_c_evolution_band=[0.60, 0.75]`, …) 그대로 둔다.

```bash
# 검증
tube-scout content policy validate --project ~/projects/2026-05-09-park-jc-nc2/
```

기대 결과: `Policy OK. composite_weights sum=1.0, all bands within [0,1].` exit 0.

---

## 3. 교수 매핑 등록

```bash
# 학과 메인 채널 측 매핑
tube-scout content professor map \
  --project ~/projects/2026-05-09-park-jc-nc2/ \
  --professor-id prof-park-jc \
  --display-name "박정광 교수" \
  --channel nursing \
  --author "박정광"

# 개인 채널 측 매핑 (cross-channel 통합 — Q4 결정 활용)
tube-scout content professor map \
  --project ~/projects/2026-05-09-park-jc-nc2/ \
  --professor-id prof-park-jc \
  --channel park-personal \
  --author __channel_owner__
```

**검증**:

```bash
tube-scout content professor show --project ~/projects/2026-05-09-park-jc-nc2/ --professor-id prof-park-jc
```

기대 출력 (rich 표):

```
professor_id: prof-park-jc
display_name: 박정광 교수
mappings:
  (nursing, 박정광)
  (park-personal, __channel_owner__)
total_videos_in_pool: 142
captions_collected: 142
captions_missing: 0
```

---

## 4. Baseline corpus bootstrap

```bash
tube-scout content baseline bootstrap \
  --project ~/projects/2026-05-09-park-jc-nc2/ \
  --professor prof-park-jc \
  --earliest-n 5 \
  --min-occurrences 3
```

기대 출력: 등록된 phrase 수 + 샘플 5개. 예:

```
Bootstrapped 14 baseline phrases for prof-park-jc.
Sample:
  1. "오늘은 무엇을 배울지 살펴봅시다" (4/5 videos)
  2. "여러분 안녕하세요 박정광입니다" (5/5 videos)
  3. "감기약 비타민 효과는 대티역 비유로 설명하면" (3/5 videos)
  ...
```

**검증**:

```bash
tube-scout content baseline list --project ~/projects/2026-05-09-park-jc-nc2/ --professor prof-park-jc | wc -l
# ≥ 14
```

---

## 5. nC2 분석 실행

```bash
tube-scout content scan \
  --project ~/projects/2026-05-09-park-jc-nc2/ \
  --mode nc2 \
  --professor prof-park-jc
```

진행률 출력 (rich):

```
[nc2/prof-park-jc] cosine cull: 142 videos → 10082 pairs
[nc2/prof-park-jc] candidates after cull: 487 / 10082
[nc2/prof-park-jc] computing time-axis: ████████████░░  342 / 487 (70%)  ETA 8m
[nc2/prof-park-jc] applying layers: 487 / 487
[nc2/prof-park-jc] complete. Suspect pairs by pattern:
   whole-same-week:        12
   scattered-same-week:    24
   whole-different-week:   18
   scattered-different-week: 31
   total:                  85 (after Layer A: 487, after Layer C demote: 65 critical+high)
   excluded by Layer D pair-whitelist: 0 (first run)
   excluded by Layer A length-cut: 422
```

총 시간: ~22분 (200 영상 미만이면 SC-001 30분 budget 안).

---

## 6. 중단·재개 검증 (FR-031)

큰 데이터셋에서 강제로 Ctrl+C 후 재실행:

```bash
# Ctrl+C 후
tube-scout content scan \
  --project ~/projects/2026-05-09-park-jc-nc2/ \
  --mode nc2 \
  --professor prof-park-jc \
  --resume
```

기대: 이미 처리된 쌍 수가 표시되고 미완료 쌍부터 재개:

```
[nc2/prof-park-jc] Resuming run nc2-prof-park-jc-20260509-2103.
Already processed: 287 / 487 candidate pairs.
Continuing from pair 288...
```

---

## 7. 보고서 생성

```bash
tube-scout report content \
  --project ~/projects/2026-05-09-park-jc-nc2/ \
  --professor prof-park-jc \
  --format html
```

생성 위치: `03_report/content/v2/{date}-prof-park-jc-nc2.html`.

기대 보고서 내용:
- 헤더: `excluded by Layer D: 0`, `excluded by Layer A: 422`, `pattern totals (12+24+18+31)`
- 섹션: 4 패턴별로 분리된 표
- 각 행: pair link, suspicion_score, grade, baseline subtraction (e.g., `−42s pre-i6=620 → post-i6=578`)
- 펼치면: 시간축 막대 시각화 (영상 A·B 각각, 일치 구간 색칠) + 일치 어구 샘플 5개

---

## 8. 검토 + 화이트리스트 누적

운영자가 1번째 의심 쌍을 검토:

```bash
tube-scout content review \
  --project ~/projects/2026-05-09-park-jc-nc2/ \
  --pattern whole-same-week
```

표 출력 후 수동 마킹:

```bash
# 오탐 마킹 (pair-level)
tube-scout content review \
  --project ~/projects/2026-05-09-park-jc-nc2/ \
  --mark 1234 FALSE_POSITIVE

# 어구 화이트리스트 (phrase-level)
tube-scout content whitelist add-phrase \
  --project ~/projects/2026-05-09-park-jc-nc2/ \
  --professor prof-park-jc \
  --phrase "이 부분은 학생 질문 답변 시간입니다" \
  --reason "강의 진행 패턴, 매학기 즉흥 발생"
```

기대: 두 명령 모두 advisory lock 획득 후 1회 갱신, exit 0.

---

## 9. 재분석에서 화이트리스트 적용 검증 (SC-005)

```bash
tube-scout content scan \
  --project ~/projects/2026-05-09-park-jc-nc2/ \
  --mode nc2 \
  --professor prof-park-jc
```

기대: 헤더에 `excluded by Layer D pair-whitelist: 1`, `excluded by Layer D phrase-whitelist hits: <N>`. 1234번 쌍은 결과에 등장하지 않음. 등록한 phrase가 포함된 쌍의 i6/i7/i8가 차감 후 값으로 갱신됨.

---

## 10. 화이트리스트 export

```bash
tube-scout content whitelist export \
  --project ~/projects/2026-05-09-park-jc-nc2/ \
  --format xlsx \
  --output ~/audit/2026-05-09-whitelist.xlsx
```

기대: pair sheet + phrase sheet 두 시트, `phrase_raw`, `reason`, `registered_at`, `registered_by` 모든 컬럼 포함.

---

## 11. 동시성 시나리오 (FR-033)

두 admin이 동시에 mark를 시도:

```bash
# Admin A 터미널
tube-scout content review --project ... --mark 1234 CONFIRMED_DUPLICATE &

# Admin B 터미널 (즉시)
tube-scout content review --project ... --mark 5678 FALSE_POSITIVE
```

기대: 두 번째 명령 중 하나는 exit 3 + 메시지: `Another administrator is currently writing to the review state. Please retry in a moment.`

---

## 12. spec 007 backward 호환 검증 (SC-009)

같은 프로젝트에서 spec 007 명령 호출:

```bash
tube-scout content compare --project ~/projects/2026-05-09-park-jc-nc2/
```

기대: spec 007 default 모드(같은 교수·교과목·주차·차시 매칭)가 그대로 작동. spec 011가 추가한 컬럼은 NULL이고, spec 007 보고서는 정상 생성됨. 자막 재수집·embedding 재산출 0건.

---

## 13. 종료 후 정리

```bash
# 분석 결과 백업
cp -a ~/projects/2026-05-09-park-jc-nc2/02_analyze/ ~/backup/2026-05-09/

# 다음 교수로 진행
tube-scout content scan --project ... --mode nc2 --professor prof-jung-ks
```

---

## Acceptance criteria mapping

| 단계 | spec.md 항목 |
|---|---|
| §3 매핑 | FR-032, US1#5, B-1 boundary |
| §4 baseline | FR-011/012, SC-004, US3#2 |
| §5 nC2 실행 | FR-001/005~009, US1#1~5, US2#1~4, SC-001, SC-002 |
| §6 resume | FR-031, SC-006 |
| §7 보고서 | FR-020~024, US5#1~4 |
| §8 검토 + 화이트리스트 | FR-014/017/018, US3#4, US4#1~4 |
| §9 재분석 검증 | FR-015, SC-005, US3#4 |
| §10 export | FR-019, US4#4 |
| §11 동시성 | FR-033 |
| §12 backward 호환 | FR-026, SC-009, B-2 boundary |
