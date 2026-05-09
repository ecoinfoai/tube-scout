# Service-Layer Contract: spec 011 functions consumed by spec 008/014 web UIs

**Feature**: 011-reuse-fullstack-subtitle
**Purpose**: spec 008 admin web UI (이미 출시) + spec 014 UI redesign (예정) 이 직접 import해 호출하는 service 함수의 시그니처 동결. Constitution IV (CLI-first) 에 따라 web UI가 이 함수들을 재구현하지 않고 그대로 호출하므로 spec 011 작업이 backend contract 변경 시 spec 008/014가 직접 영향받는다.

본 contract는 contract 테스트 (`tests/contract/test_service_layer_contract.py`) 의 ground truth다.

---

## 1. Module: `tube_scout.services.nc2_matcher`

```python
def generate_nc2_pairs(
    professor_id: str,
    db_path: Path,
    captions_dir: Path,
    cosine_cull_threshold: float,
) -> list[CandidatePair]:
    """Generate nC2 candidate pairs for a single professor's caption pool.

    Performs cheap I-2 cosine cull before returning candidates so that
    downstream segment alignment is bounded.

    Args:
        professor_id: Identifier registered in professor_pool.
        db_path: SQLite content_reuse.db path.
        captions_dir: Directory of caption JSON files (spec 010 output).
        cosine_cull_threshold: Pairs below this cosine similarity are dropped.

    Returns:
        List of CandidatePair with (video_id_a, video_id_b, cosine).
    """

def get_caption_pool(professor_id: str, db_path: Path) -> CaptionPool:
    """Resolve all video refs for a professor across mapped channels."""
```

**Stability**: signature는 minor 추가만 허용 (예: 새 옵셔널 매개변수 추가 OK, 기존 매개변수 제거 NO).

---

## 2. Module: `tube_scout.services.time_axis_indicators`

```python
def compute_time_axis(
    pair: CandidatePair,
    captions_a: list[Segment],
    captions_b: list[Segment],
) -> TimeAxisResult:
    """Compute I-6 (longest contiguous), I-7 (distribution), I-8 (position diversity).

    Args:
        pair: Candidate pair after cosine cull.
        captions_a: Caption segments for video A (spec 010 schema).
        captions_b: Caption segments for video B.

    Returns:
        TimeAxisResult containing I-6/I-7/I-8 plus the list of MatchSpan.
    """

def find_match_spans(
    captions_a: list[Segment],
    captions_b: list[Segment],
    normalize: Callable[[str], str],
) -> list[MatchSpan]:
    """Find aligned match spans using normalized exact match + greedy extension."""
```

---

## 3. Module: `tube_scout.services.layer_defense`

```python
def apply_layers(
    comparison: ComparisonResult,
    spans: list[MatchSpan],
    professor_id: str,
    db_path: Path,
    policy: PolicyConfig,
) -> tuple[ComparisonResult, list[MatchSpan]]:
    """Apply Layer A → B → D (phrase) → C in order, return updated comparison + spans.

    Side-effects: none (pure transformation; persistence happens in caller).

    Layer attribution is recorded inside ComparisonResult.layer_attribution.
    """
```

**Layer 순서**: A(길이 컷) → B(baseline 차감) → D-phrase(화이트리스트 차감) → C(등급 demote). D-pair는 caller(scan)가 사전 필터로 적용 (이미 FALSE_POSITIVE 마킹된 쌍은 measure 시도 안 함).

---

## 4. Module: `tube_scout.services.baseline_corpus`

```python
def bootstrap_baseline(
    professor_id: str,
    db_path: Path,
    captions_dir: Path,
    earliest_n: int = 5,
    min_occurrences: int = 3,
    registered_by: str = "system",
) -> BaselineBootstrapReport:
    """Seed baseline corpus from a professor's earliest videos.

    Idempotent: re-runs add to occurrences, do not duplicate phrases.
    """

def add_baseline_phrase(
    professor_id: str,
    phrase_raw: str,
    db_path: Path,
    source_video_ids: list[str] | None,
    registered_by: str,
) -> BaselinePhrase:
    """Manually register a recurring phrase. Normalization applied automatically."""

def list_baseline(professor_id: str | None, db_path: Path) -> list[BaselinePhrase]:
    """List baseline phrases, filtered by professor if given."""

def remove_baseline_phrase(
    professor_id: str,
    phrase_raw: str,
    db_path: Path,
) -> bool:
    """Remove. Returns True if removed, False if not found."""

def subtract_baseline(
    professor_id: str,
    spans: list[MatchSpan],
    db_path: Path,
) -> tuple[list[MatchSpan], float]:
    """Subtract baseline-matching spans, return (remaining spans, subtracted seconds)."""
```

---

## 5. Module: `tube_scout.services.phrase_whitelist`

```python
def normalize_phrase(text: str) -> str:
    """Apply NFKC + lowercase + punctuation strip + whitespace collapse + trim.

    R-7 normalization. Single source of truth used by both whitelist matching
    and baseline corpus matching.
    """

def add_pair_whitelist(
    source_video_id: str,
    target_video_id: str,
    reason: str,
    db_path: Path,
    registered_by: str,
) -> int:
    """Mark a comparison pair FALSE_POSITIVE (spec 007 review_status reuse).

    Returns: comparison_results.id of the affected row.
    Raises: ValueError if pair not found.
    """

def add_phrase_whitelist(
    professor_id: str,
    phrase_raw: str,
    reason: str,
    db_path: Path,
    registered_by: str,
) -> WhitelistPhraseEntry:
    """Add a phrase to per-professor whitelist."""

def list_whitelist(
    db_path: Path,
    professor_id: str | None = None,
    kind: Literal["pair", "phrase", "both"] = "both",
) -> WhitelistView:
    """List entries; admin UI uses this for the audit table."""

def export_whitelist(
    db_path: Path,
    fmt: Literal["csv", "xlsx", "markdown"],
    output_path: Path,
) -> Path:
    """Write whitelist to disk in the requested format. Returns the path."""

def remove_whitelist(
    db_path: Path,
    kind: Literal["pair", "phrase"],
    entry_id: int,
) -> bool:
    """Remove entry. For pair, resets review_status to UNREVIEWED."""
```

---

## 6. Module: `tube_scout.services.pair_checkpoint`

```python
def start_run(
    professor_id: str,
    matching_mode: Literal["M-default", "M-nC2"],
    pair_count_total: int,
    db_path: Path,
) -> str:
    """Insert pair_checkpoint row, return run_id."""

def iterate_unfinished_pairs(
    pool: CaptionPool,
    matching_mode: Literal["M-default", "M-nC2"],
    db_path: Path,
) -> Iterator[VideoPairRef]:
    """Yield only pairs not already present in comparison_results.

    Idempotent restart: re-running after interruption resumes from the
    next unfinished pair.
    """

def mark_pair_done(run_id: str, db_path: Path) -> None:
    """Increment pair_count_done and update last_pair_at."""

def finalize_run(
    run_id: str,
    db_path: Path,
    status: Literal["completed", "aborted"],
) -> PairCheckpoint:
    """Mark run complete (or aborted) and return final state."""
```

---

## 7. Module: `tube_scout.services.professor_resolver`

```python
def resolve_caption_pool(professor_id: str, db_path: Path) -> CaptionPool:
    """Walk professor_pool_membership rows and return all video refs.

    Falls back to channel-only pool if no mapping exists for a channel.
    """

def map_professor(
    professor_id: str,
    display_name: str,
    channel_alias: str,
    author_marker: str,
    db_path: Path,
    registered_by: str,
    note: str | None = None,
) -> ProfessorMapping:
    """Register or extend a professor mapping. Idempotent on duplicate."""

def unmap_professor(
    professor_id: str,
    channel_alias: str,
    author_marker: str,
    db_path: Path,
) -> bool:
    """Remove a single membership row. Returns True if removed."""

def list_professors(db_path: Path) -> list[ProfessorMapping]:
    """List all registered professor mappings."""
```

---

## 8. Module: `tube_scout.services.pattern_classifier`

```python
def classify_reuse_pattern(
    comparison: ComparisonResult,
    durations: tuple[float, float],
    same_week: bool,
    policy: PolicyConfig,
) -> ReusePatternLabel:
    """Return one of 4 pattern labels using I-6 ratio + I-7 distribution + week flag."""
```

---

## 9. Module: `tube_scout.services.advisory_lock`

```python
@contextmanager
def layer_d_write_lock(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Acquire SQLite BEGIN IMMEDIATE write lock for Layer D mutations.

    Raises ConcurrentWriteRejected if lock unavailable; the caller's
    user-facing surface (CLI / web) is responsible for translating this
    to exit code 3 / HTTP 409 with the standard English message.
    """

class ConcurrentWriteRejected(RuntimeError):
    """Raised when another administrator's write is in progress."""
```

---

## 10. Backwards-compatible 함수 정책

다음 함수는 **deprecate되지 않으며 기존 시그니처가 보존된다** — spec 008 web UI가 이미 사용 중:

- `services.content_comparator.compare_pair(...)` (spec 007) — `matching_mode` 매개변수 추가는 keyword-only, 기본값 `M-default` 로 backward-compat.
- `services.content_comparator.run_full_pipeline(...)` (spec 007 scan) — 마찬가지.
- `storage.content_db.*` 의 모든 spec 007 함수 — 시그니처 동결.

신규 컬럼은 ORM 레이어(Pydantic `ComparisonResult`)에서 옵셔널로 노출되어, 신구 caller 모두 작동.

---

## 11. Contract test의 책임

`tests/contract/test_service_layer_contract.py` 가 다음을 강제:

1. 위 함수들이 import 가능 (이름·모듈 경로 일치).
2. 함수 시그니처(매개변수명, 타입, 기본값)가 본 문서와 동일.
3. 신규 함수의 docstring이 Google style + English (Constitution III).
4. 신규 예외 클래스가 정의되어 있음.

시그니처 변경 시 이 contract 파일 + spec 008(추후 spec 014) 양쪽을 PR 단위로 동시 갱신해야 한다.
