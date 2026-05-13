# Contract: services/nc2_matcher.py + time_axis_indicators.py + layer_defense.py + pattern_classifier.py

**Modules** (모두 기존 spec 011 부분 구현 — 본 spec에서 완성):
- `src/tube_scout/services/nc2_matcher.py`
- `src/tube_scout/services/time_axis_indicators.py`
- `src/tube_scout/services/layer_defense.py`
- `src/tube_scout/services/pattern_classifier.py`

**Spec FR mapping**: FR-028~FR-034.
**Boundary**: B-4 (spec 011 시그니처 권위), B-6/B-7 (음원 지문).

---

## A. nC2 매칭 모드 (FR-029)

```python
from collections.abc import Iterator
from tube_scout.models.content import VideoPair, ComparisonResult

def generate_nc2_pairs(
    professor: str,
    db: ContentDB,
    *,
    layer_a_min_seconds: float = 30.0,
) -> Iterator[VideoPair]:
    """Generate all unique video pairs (nC2) within one professor's video pool.

    Steps:
      1. Query video_metadata + professor_pool_membership to enumerate 1 professor's videos.
      2. For each (v_i, v_j) with i < j (lexical order on video_id):
         a. Check pair_checkpoint — skip if already analyzed (with --resume).
         b. Apply Layer A length filter (skip pairs where shorter video < layer_a_min_seconds).
         c. Yield VideoPair.

    Args:
        professor: professor name (matches professor_pool.professor).
        db: ContentDB wrapper.
        layer_a_min_seconds: 짧은 영상 임계.

    Yields:
        VideoPair(source_video_id, target_video_id) ordered (source < target by video_id).
    """

def run_nc2_analysis(
    professor: str,
    channel_alias: str,
    db: ContentDB,
    *,
    matching_mode: Literal["M-default", "M-nC2"] = "M-default",
    layer_a_min_seconds: float = 30.0,
    layer_b_threshold: float = 0.30,
    resume: bool = False,
    force: bool = False,
    progress: ProgressReporter | None = None,
) -> AnalysisResult:
    """Execute analysis for one professor (M-default or M-nC2).

    Side effects:
        - INSERT/UPDATE rows in comparison_results
        - INSERT rows in match_spans
        - UPDATE pair_checkpoint per pair

    Returns:
        AnalysisResult with summary counters.
    """
```

---

## B. 시간축 지표 I-6 / I-7 / I-8 (FR-028)

```python
from tube_scout.models.content import MatchSpan

def compute_i6_longest_contiguous(spans: list[MatchSpan]) -> float:
    """I-6: 가장 긴 연속 매칭 구간의 길이(초).

    Args:
        spans: pair의 모든 매칭 구간 (시작 시각순 정렬 가정).

    Returns:
        max(span.span_length) — 비어 있으면 0.0.
    """

def compute_i7_distribution_dispersion(spans: list[MatchSpan]) -> float:
    """I-7: 매칭 구간 길이 분포의 dispersion (Gini-like 또는 entropy).

    Returns:
        [0, 1] — 0=한 구간 집중, 1=균등 분산.

    Algorithm (spec 011 권위):
        - 각 span_length를 sorted, 누적분포(CDF) 계산.
        - dispersion = 1 - Gini coefficient (또는 normalized entropy — spec 011 선택).
    """

def compute_i8_position_diversity(
    spans: list[MatchSpan],
    src_duration: float,
    tgt_duration: float,
) -> float:
    """I-8: 매칭 위치의 시간축 다양성.

    Returns:
        [0, 1] — 매칭이 영상 시간축 전체에 균등 분포 시 1.0, 한 구간 집중 시 0.0.

    Algorithm:
        - source/target 각각의 시간축을 N bin (예: 10 bin)으로 나눔.
        - 매칭이 등장한 bin 수 / N.
        - source / target 평균.
    """

def compute_i8_half_split(
    spans: list[MatchSpan],
    src_duration: float,
) -> tuple[float, float]:
    """I-8을 영상 전반부/후반부로 분리 측정 — tail-update 패턴 검출용.

    Returns:
        (i8_first_half, i8_second_half) tuple. 각각 [0, 1].
    """
```

---

## C. 4계층 오탐 방어 (FR-030)

```python
def apply_layer_a(spans: list[MatchSpan], min_seconds: float) -> list[MatchSpan]:
    """Layer A — span_length < min_seconds 인 span 제거."""

def apply_layer_b(
    spans: list[MatchSpan],
    prof_baseline: BaselineCorpus,
    *,
    threshold: float = 0.30,
) -> list[MatchSpan]:
    """Layer B — 한 교수 corpus에 ≥ threshold 등장하는 n-gram이 다수인 span 제거.

    prof_baseline 은 spec 011 services/baseline_corpus.py 의 BaselineCorpus 인스턴스.
    """

def apply_layer_c(
    spans: list[MatchSpan],
    dept_idf: IDFCorpus,
    *,
    min_idf: float = 1.0,
) -> list[MatchSpan]:
    """Layer C — 학과 전체에서 IDF < min_idf 인 흔한 용어 down-weight."""

def apply_layer_d(
    pair_id: str,
    db: ContentDB,
) -> Literal["CONFIRMED_DUPLICATE", "FALSE_POSITIVE", None]:
    """Layer D — operator-curated review_status 조회. None=미라벨."""
```

---

## D. 패턴 분류 (FR-031)

```python
from tube_scout.models.reuse_v2 import ReusePatternLabel

def classify(
    pair: ComparisonResult,
    src_duration: float,
    tgt_duration: float,
    audio_fp_hamming: int | None,
    *,
    same_week: bool,
    audio_fp_hamming_threshold: int = 50,  # Phase 3 측정 후 확정
) -> ReusePatternLabel:
    """Classify pair into one of 6 patterns.

    Decision tree:
        if i6_longest_contiguous / min(src_duration, tgt_duration) >= 0.80:
            scope = "whole"
        else:
            scope = "scattered"
        if same_week:
            base = f"{scope}-same-week"
        else:
            base = f"{scope}-different-week"

        # 신설 패턴 override
        if audio_fp_hamming is not None and audio_fp_hamming > audio_fp_hamming_threshold:
            if pair.i2_cosine_similarity >= 0.85 and pair.i6_longest_contiguous_seconds / min_dur >= 0.50:
                return RE_RECORDED_SAME_CONTENT

        i8_first, i8_second = compute_i8_half_split(spans, src_duration)
        if i8_first >= 0.85 and i8_second <= 0.15:
            return TAIL_UPDATE

        return ReusePatternLabel(base)
    """
```

**Audio fp hamming threshold (Phase 3 측정 deferred)**: 9개 PoC 영상으로 동일/이질 영상 hamming 분포 측정 후 cutoff 결정. 기본 50은 출발점.

---

## E. AnalysisResult

```python
class AnalysisResult(BaseModel):
    professor: str
    channel_alias: str
    matching_mode: Literal["M-default", "M-nC2"]
    total_pairs_generated: int
    pairs_culled_layer_a: int
    pairs_analyzed: int
    pairs_failed: int
    elapsed_seconds: float
    pattern_distribution: dict[str, int]  # {pattern_label: count}
```

---

## F. CLI 통합

`cli/analyze.py::content_reuse` 함수가 `run_nc2_analysis`를 호출. 진행 상황은 ProgressReporter (R-7)로 stage `'analyze'` 출력. 매 100쌍마다 audit_writer.append_row("analyze", {...}).

---

## 테스트 진입점

- `tests/contract/test_nc2_matcher_contract.py`:
  - `test_generate_nc2_pairs_returns_n_choose_2`
  - `test_generate_nc2_pairs_skips_layer_a_short`
  - `test_run_nc2_analysis_resumable_via_checkpoint`
- `tests/unit/test_time_axis_indicators.py`:
  - `test_i6_longest_contiguous_single_span`
  - `test_i6_returns_zero_on_empty`
  - `test_i7_dispersion_balanced_vs_concentrated`
  - `test_i8_position_diversity_full_coverage_returns_1`
  - `test_i8_half_split_returns_two_values_summing_to_total`
- `tests/unit/test_pattern_classifier.py`:
  - `test_classify_whole_same_week`
  - `test_classify_scattered_different_week`
  - `test_classify_re_recorded_same_content_when_audio_differs`
  - `test_classify_tail_update_when_i8_drops`
- `tests/integration/test_nc2_analysis_full.py` (`@pytest.mark.slow`):
  - 9 PoC 영상으로 36쌍 mini-nC2 end-to-end. comparison_results + match_spans 영속 검증.
- `tests/integration/test_layer_defense_e2e.py`:
  - prof_baseline → apply_layer_b 적용 결과 검증.
