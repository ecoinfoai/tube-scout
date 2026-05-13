# Contract: services/evidence_score.py

**Module**: `src/tube_scout/services/evidence_score.py` (신규)
**Spec FR mapping**: FR-003, FR-004.
**Boundary**: 본 spec 신규. Takeout ingestion 어댑터가 import.

---

## 함수 시그니처

```python
from pathlib import Path
from typing import Literal

ConfidenceBucket = Literal["high", "medium", "ambiguous"]

class EvidenceSignals(BaseModel):
    """Per-(mp4, video_id) candidate signal breakdown."""
    exact_title_match: bool             # +40
    normalized_title_match: bool        # +30 (only if not exact)
    duration_match_within_1s: bool      # +25
    size_ratio_plausible: bool          # +5
    mtime_match_within_1d: bool         # +5

    @property
    def score(self) -> int:
        s = 0
        if self.exact_title_match:
            s += 40
        elif self.normalized_title_match:
            s += 30
        if self.duration_match_within_1s:
            s += 25
        if self.size_ratio_plausible:
            s += 5
        if self.mtime_match_within_1d:
            s += 5
        return s

class MappingDecision(BaseModel):
    mp4_path: Path
    video_id: str | None              # None if no candidate scored high enough
    score: int
    confidence: ConfidenceBucket | None
    signals: EvidenceSignals | None
    candidates: list[tuple[str, int]]  # top-3 (video_id, score)

DEFAULT_HIGH_THRESHOLD: int = 65    # idea §7.1 출발점, Phase 1 측정 후 commit
DEFAULT_MEDIUM_THRESHOLD: int = 40

def score_mp4_candidates(
    mp4_path: Path,
    video_meta_list: list[VideoMetadata],
    *,
    duration_tolerance_seconds: float = 1.0,
    mtime_tolerance_days: float = 1.0,
) -> list[tuple[str, EvidenceSignals]]:
    """Compute evidence signals for every (mp4, video_id) candidate.

    Args:
        mp4_path: Takeout mp4 절대 경로.
        video_meta_list: 채널 video_metadata 후보 list.
        duration_tolerance_seconds: ±1초 (기본).
        mtime_tolerance_days: ±1일 (기본).

    Returns:
        list of (video_id, EvidenceSignals) for every candidate
        (1 row per video_meta, score may be 0).
    """

def decide_mapping(
    mp4_path: Path,
    video_meta_list: list[VideoMetadata],
    *,
    high_threshold: int = DEFAULT_HIGH_THRESHOLD,
    medium_threshold: int = DEFAULT_MEDIUM_THRESHOLD,
) -> MappingDecision:
    """Decide the best mapping for one mp4 using the evidence score.

    Tie-breaking:
        - Highest score wins.
        - Equal top scores → ambiguous (multiple candidates).
        - Score < medium_threshold → no mapping (confidence=None, video_id=None).

    Args:
        mp4_path: 단일 mp4 파일.
        video_meta_list: 동일 채널의 video_metadata 후보 list.
        high_threshold: high 분류 임계 (기본 65).
        medium_threshold: medium 분류 임계 (기본 40).

    Returns:
        MappingDecision with chosen video_id (or None) + signal breakdown.
    """
```

---

## 신호 계산 디테일

### `exact_title_match`

```python
def _exact_title_match(mp4_filename: str, video_title: str) -> bool:
    stem = Path(mp4_filename).stem
    return stem == video_title
```

### `normalized_title_match`

```python
_NORMALIZE_PATTERN = re.compile(r"[\s\-_.,()\[\]?!~]+")

def _normalize_for_match(s: str) -> str:
    return _NORMALIZE_PATTERN.sub("", s).lower()

def _normalized_title_match(mp4_filename: str, video_title: str) -> bool:
    return _normalize_for_match(Path(mp4_filename).stem) == _normalize_for_match(video_title)
```

OS 255자 절단된 mp4 파일명은 정확 일치 실패하지만 normalized 일치는 prefix match도 허용:

```python
def _normalized_title_match(mp4_filename: str, video_title: str) -> bool:
    norm_stem = _normalize_for_match(Path(mp4_filename).stem)
    norm_title = _normalize_for_match(video_title)
    if norm_stem == norm_title:
        return True
    # 255자 절단 대응 — mp4 stem이 title의 prefix면 일치 인정 (단 길이 ≥ 50자, 정확도 가드)
    if len(norm_stem) >= 50 and norm_title.startswith(norm_stem):
        return True
    return False
```

### `duration_match_within_1s`

```python
def _duration_match(mp4_path: Path, video_duration_s: float, tol_s: float) -> bool:
    actual = _probe_duration_via_ffprobe(mp4_path)
    return abs(actual - video_duration_s) <= tol_s
```

`_probe_duration_via_ffprobe` 는 ffmpeg `ffprobe -v error -show_entries format=duration -of csv=p=0 <mp4>` 호출. 실패 시 False(신호 부재).

### `size_ratio_plausible`

```python
def _size_ratio_plausible(mp4_path: Path, duration_s: float) -> bool:
    """Sanity check — bytes/second 비율이 합리적 범위인지.

    Takeout mp4의 일반적 비율: 0.5 MB/s ~ 10 MB/s.
    """
    size_bytes = mp4_path.stat().st_size
    ratio = size_bytes / duration_s if duration_s > 0 else 0
    return 0.5e6 <= ratio <= 10e6
```

### `mtime_match_within_1d`

```python
def _mtime_match(mp4_path: Path, created_at: datetime, tol_days: float) -> bool:
    mp4_mtime = datetime.fromtimestamp(mp4_path.stat().st_mtime, tz=UTC)
    delta = abs((mp4_mtime - created_at).total_seconds())
    return delta <= tol_days * 86400
```

**주의**: mtime은 +5 가중치(보조 신호) — 압축 해제·복사·외장 디스크로 손상 가능. 단독으로는 65/40 임계 통과 불가.

---

## Manual override CSV 통합 (FR-006)

`takeout_ingest.py` 가 `_manual_mappings.csv` 를 읽어 본 함수 호출 전에 매핑 결정:

```python
def resolve_manual_override(mp4_path: Path, manual_map: dict[str, str]) -> str | None:
    """Return video_id from _manual_mappings.csv if mp4_path is registered."""
    return manual_map.get(mp4_path.name)
```

`decide_mapping` 은 manual override가 없는 mp4에만 호출됨.

---

## 테스트 진입점

- `tests/contract/test_evidence_score_contract.py`:
  - `test_score_mp4_candidates_returns_per_candidate_signals`
  - `test_decide_mapping_signature`
- `tests/unit/test_evidence_signals.py`:
  - `test_exact_title_match_full_string`
  - `test_normalized_title_match_handles_spaces_and_punctuation`
  - `test_normalized_title_match_prefix_50_chars` (255자 절단 시뮬레이션)
  - `test_duration_match_within_tolerance`
  - `test_duration_match_outside_tolerance_false`
  - `test_size_ratio_plausible_range`
  - `test_mtime_match_within_1d`
  - `test_score_computation_all_signals` (40+25+5+5 = 75)
  - `test_score_computation_normalized_replaces_exact` (+30 not +70)
- `tests/unit/test_decide_mapping.py`:
  - `test_high_confidence_when_score_above_65`
  - `test_medium_confidence_when_40_to_65`
  - `test_no_mapping_when_below_40`
  - `test_ambiguous_when_two_top_candidates_tie`
- `tests/integration/test_evidence_score_takeout_9_videos.py`:
  - 1차 Takeout sanitized 9-video fixture → 자동화율 측정 (Phase 1 measurement task).

---

## Phase 1 measurement task

`_workspace/measurement/evidence_score_phase1.md` 에 다음 결과 commit:
- score 분포 히스토그램 (9 videos × N candidates).
- high/medium/ambiguous 카운트.
- 자동화율 = (high + medium) / total.
- mtime 신호의 실측 기여도 (mtime이 손상된 경우 vs 정확한 경우 score 차).
- 결과로 high_threshold / medium_threshold / 가중치 튜닝 권장사항 commit.
