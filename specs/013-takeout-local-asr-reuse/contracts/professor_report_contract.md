# Contract: reporting/professor_nc2.py + templates/professor_nC2_report.html

**Modules**:
- `src/tube_scout/reporting/professor_nc2.py` (신규)
- `src/tube_scout/reporting/templates/professor_nC2_report.html` (신규 jinja2 템플릿)

**Spec FR mapping**: FR-035~FR-039.
**Boundary**: B-9 (spec 006 report bundle 인프라).

---

## 함수 시그니처

```python
from pathlib import Path
from typing import Literal

ReportFormat = Literal["pdf", "html", "both"]
SortMetric = Literal["i2-cosine", "i6-longest-contiguous", "i7-distribution-dispersion", "i8-position-diversity", "audio-fp-hamming"]

class AppendixThresholds(BaseModel):
    """Per-metric appendix thresholds (C-3 Phase 3 운영, deferred aggregate score)."""
    i2_cosine: float | None = None
    i6_longest_contiguous: float | None = None
    i7_distribution_dispersion: float | None = None
    i8_position_diversity: float | None = None
    audio_fp_hamming: int | None = None

def render_professor_nc2_report(
    professor: str,
    channel_alias: str,
    db: ContentDB,
    output_dir: Path,
    *,
    matching_mode: Literal["M-default", "M-nC2"] = "M-nC2",
    top_k: int = 50,
    sort_by: SortMetric = "i2-cosine",
    appendix_thresholds: AppendixThresholds = AppendixThresholds(),
    output_format: ReportFormat = "both",
) -> ReportResult:
    """Render per-professor M-nC2 reuse report (PDF + HTML).

    Pre-conditions:
        - comparison_results 에 (professor, matching_mode) 조합 row 존재
        - match_spans 에 대응 row 존재 (1:1 detail 페이지용)

    Steps:
      1. Query comparison_results + video_metadata + audio_fingerprint JOIN.
      2. Sort by --sort-by metric, slice top_k.
      3. Per-metric distribution histograms (5 axis) → plotly static image.
      4. Pattern statistics (6 patterns).
      5. Layer A/B/C/D defense application counters.
      6. Apply appendix_thresholds (OR semantics) → filter pairs for appendix.
      7. Render jinja2 template (HTML).
      8. If format ∈ {pdf, both}: weasyprint HTML → PDF (lazy import).
      9. Write audit `report_audit.csv` row.

    Returns:
        ReportResult — output paths + summary counts.
    """

class ReportResult(BaseModel):
    professor: str
    channel_alias: str
    html_path: Path | None
    pdf_path: Path | None
    pair_count: int
    top_k_count: int
    appendix_count: int
    pattern_distribution: dict[str, int]
    generated_at: datetime
```

---

## Template structure (`professor_nC2_report.html`)

본문 (10~20쪽):

1. **표지**: 채널 alias / 교수명 / 분석 기간(영상 created_at 범위) / 영상 수 / 비교 쌍 수 / 생성 일시.
2. **채널 요약**: 과목별 영상 분포(`video_metadata.category` 그룹) + 연도별 추이 차트.
3. **per-metric 분포 히스토그램 5개**: i2_cosine / i6_longest / i7_dispersion / i8_diversity / audio_fp_hamming. plotly 정적 png 임베드.
4. **Top-K 의심 쌍 목록**: 운영자 `--sort-by` 축으로 내림차순 정렬한 K개. 각 행: pair_id, source 제목, target 제목, 8 metric scores, audio_fp_hamming, reuse_pattern, source_type_pair, review_status.
5. **패턴별 통계**: 6 패턴(기존 4 + 신설 2) 분포 + 시각화.
6. **4계층 오탐 방어 적용 내역**: Layer A로 cull된 쌍 수, Layer B로 down-weight된 span 수, Layer C IDF 적용 통계, Layer D 화이트리스트 카운트.

부록 (분량 가변):

7. **임계 이상 의심 쌍 1:1 상세 페이지**: `appendix_thresholds` OR semantics로 필터된 쌍만. 한 쌍당 한 페이지:
   - 두 영상 메타 (제목, duration, privacy_status, created_at)
   - 8 metric + audio_fp 점수 표
   - **시간축 alignment 뷰**: 매칭 구간을 두 영상의 시간축에 색상 하이라이트
   - **시간축 프로필 풀 차트**: per-bin match density (I-8 도출 데이터)
   - **음원 지문 alignment 시각화**: best_offset, overlap_seconds 표시
   - **반론(counter-evidence)**: Layer A/B/C/D 적용 내역 per pair

---

## Report tone enforcement (FR-037)

템플릿 헤더 주석:

```
{# Report tone enforcement (spec.md FR-037 / SC-007):
   - 단정 라벨 어휘 사용 금지: "재활용 확정", "위반", "표절", "복제"
   - 보류형 어휘 사용: "의심 근거", "검토 우선순위 상위", "주의 필요"
   - 각 의심 쌍 항목은 evidence(정량) + counter-evidence(Layer 적용) 동시 표시
#}
```

추가 정적 lint 테스트 (`tests/integration/test_report_tone.py`):
- 생성된 HTML에서 단정 라벨 어휘 검출 시 fail.
- 의심 쌍 entry당 evidence + counter-evidence 둘 다 존재 확인.

---

## Per-metric appendix threshold (C-3)

`appendix_thresholds` 필드별 OR semantics — 한 쌍이라도 하나의 임계를 초과하면 부록 진입:

```python
def passes_appendix(pair: ComparisonResultRow, t: AppendixThresholds) -> bool:
    if t.i2_cosine is not None and pair.i2_cosine_similarity >= t.i2_cosine:
        return True
    if t.i6_longest_contiguous is not None and pair.i6_longest_contiguous_seconds >= t.i6_longest_contiguous:
        return True
    if t.i7_distribution_dispersion is not None and pair.i7_distribution_dispersion >= t.i7_distribution_dispersion:
        return True
    if t.i8_position_diversity is not None and pair.i8_position_diversity >= t.i8_position_diversity:
        return True
    if t.audio_fp_hamming is not None and pair.audio_fp_hamming is not None and pair.audio_fp_hamming >= t.audio_fp_hamming:
        return True
    return False
```

운영 첫 30일 임계 미설정 시(`appendix_thresholds`가 모두 None) → 모든 쌍 부록 진입. spec.md FR-038 default.

---

## PDF 렌더링

```python
def _render_pdf(html_str: str, pdf_path: Path) -> None:
    try:
        from weasyprint import HTML
    except ImportError as e:
        raise ImportError(
            "weasyprint is not installed. Install with: uv sync --extra pdf"
        ) from e
    HTML(string=html_str).write_pdf(pdf_path)
```

weasyprint는 `[project.optional-dependencies] pdf` extras. lazy import.

---

## 테스트 진입점

- `tests/contract/test_professor_report_contract.py`:
  - `test_render_professor_nc2_report_signature_matches_contract`
  - `test_report_result_includes_pattern_distribution`
- `tests/unit/test_appendix_threshold_passes.py`:
  - `test_passes_appendix_or_semantics_single_axis`
  - `test_passes_appendix_no_thresholds_admits_all`
- `tests/integration/test_professor_nc2_report.py` (`@pytest.mark.slow`):
  - mini-nC2 36쌍 → HTML 생성 → 단정 라벨 어휘 0건 검증.
  - 부록 임계 1축 설정 → 임계 이상 쌍만 부록 진입 검증.
- `tests/integration/test_report_tone.py`:
  - SC-007 회귀 — 단정 라벨 어휘 grep, 검출 시 fail.
- `tests/integration/test_report_pdf_optional_extra.py`:
  - weasyprint 미설치 시 ImportError actionable 메시지.
