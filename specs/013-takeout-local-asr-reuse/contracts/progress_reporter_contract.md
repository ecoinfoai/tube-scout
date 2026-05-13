# Contract: services/progress_reporter.py

**Module**: `src/tube_scout/services/progress_reporter.py` (신규)
**Spec FR mapping**: FR-061.
**Boundary**: 본 spec 신규. CLI 명령들이 import.

---

## 함수·클래스 시그니처

```python
from contextlib import AbstractContextManager
from typing import Protocol

class ProgressReporter(Protocol):
    """Stage-aware progress reporter (TTY/non-TTY auto-adaptive)."""

    def update(self, video_id: str, n: int) -> None:
        """Update progress.

        Args:
            video_id: 현재 처리 중인 영상 ID (또는 pair_id for analyze stage).
            n: 1-based 진행 카운트.
        """

    def __enter__(self) -> "ProgressReporter": ...
    def __exit__(self, exc_type, exc_val, exc_tb) -> bool | None: ...

def make_progress_reporter(
    stage: str,
    total: int,
    *,
    force_tty: bool | None = None,
    nontty_throttle_n: int = 1,
    nontty_throttle_seconds: float = 60.0,
) -> ProgressReporter:
    """Create a stage-aware progress reporter, auto-detecting TTY.

    Args:
        stage: 'takeout_ingest', 'audio_extract', 'transcripts', 'fingerprint',
               'normalize', 'analyze', 'report', 'kb_export'.
        total: 전체 작업 항목 수 (영상 수 또는 쌍 수).
        force_tty: None=자동 감지(sys.stdout.isatty()), True/False=강제 분기 (테스트용).
        nontty_throttle_n: 비-TTY 모드에서 N 항목마다 한 줄 출력.
        nontty_throttle_seconds: 비-TTY 모드에서 K초마다 한 줄 출력 (둘 중 짧은 쪽 발동).

    Returns:
        TTYProgressReporter (rich.progress) 또는 NonTTYProgressReporter (structured log).
    """
```

---

## TTY mode (rich.progress)

```python
class TTYProgressReporter:
    def __init__(self, stage: str, total: int):
        from rich.progress import (
            Progress, SpinnerColumn, BarColumn, TextColumn,
            TimeElapsedColumn, TimeRemainingColumn, TaskProgressColumn,
        )
        self._stage = stage
        self._total = total
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn(f"[bold blue]{stage}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("•"),
            TextColumn("{task.fields[video_id]}"),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
        )
        self._task_id = None

    def __enter__(self):
        self._progress.__enter__()
        self._task_id = self._progress.add_task("", total=self._total, video_id="")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._progress.__exit__(exc_type, exc_val, exc_tb)

    def update(self, video_id: str, n: int):
        self._progress.update(self._task_id, completed=n, video_id=video_id)
```

---

## non-TTY mode (structured log)

```python
class NonTTYProgressReporter:
    def __init__(self, stage: str, total: int, throttle_n: int, throttle_seconds: float):
        self._stage = stage
        self._total = total
        self._throttle_n = throttle_n
        self._throttle_seconds = throttle_seconds
        self._start_time: float | None = None
        self._last_emit_time: float = 0.0
        self._last_emit_n: int = 0

    def __enter__(self):
        self._start_time = time.monotonic()
        sys.stdout.write(f"[{self._stage}] starting total={self._total}\n")
        sys.stdout.flush()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.monotonic() - (self._start_time or 0)
        sys.stdout.write(f"[{self._stage}] finished elapsed={elapsed:.1f}s\n")
        sys.stdout.flush()
        return None

    def update(self, video_id: str, n: int):
        now = time.monotonic()
        if (n - self._last_emit_n) < self._throttle_n and (now - self._last_emit_n) < self._throttle_seconds and n < self._total:
            return  # throttle
        elapsed = now - (self._start_time or now)
        eta = (self._total - n) * (elapsed / n) if n > 3 else 0.0  # ETA shown from 4th item onwards (≥3 samples for stable estimate)
        eta_str = f"ETA={eta:.0f}s" if eta > 0 else "ETA=?"
        sys.stdout.write(
            f"[{self._stage}] video_id={video_id} N={n}/total={self._total} elapsed={elapsed:.1f}s {eta_str}\n"
        )
        sys.stdout.flush()
        self._last_emit_time = now
        self._last_emit_n = n
```

ETA 계산: 첫 3 항목 동안은 표시 0(`ETA=?`) — sample 부족 시 부정확.

---

## 사용 패턴

`cli/collect.py::process_audio` 의사코드:

```python
videos = select_videos(...)
with make_progress_reporter("audio_extract", total=len(videos)) as progress:
    for i, video in enumerate(videos, start=1):
        with WavLifecycle(...) as wav_path:
            extract_chromaprint_fingerprint(wav_path)
            transcribe_audio(wav_path, ...)
        progress.update(video.video_id, i)
```

`cli/analyze.py::content_reuse` 의사코드 (analyze stage):

```python
pairs = list(generate_nc2_pairs(professor, db))
with make_progress_reporter("analyze", total=len(pairs), nontty_throttle_n=100) as progress:
    for i, pair in enumerate(pairs, start=1):
        compare_pair(pair, ...)
        progress.update(pair.pair_id, i)
```

19,900쌍 분석 시 비-TTY 모드는 매 100쌍 또는 60초마다 한 줄 — cron log ~200줄 수준.

---

## 테스트 진입점

- `tests/contract/test_progress_reporter_contract.py`:
  - `test_make_progress_reporter_returns_tty_when_stdout_is_tty`
  - `test_make_progress_reporter_returns_nontty_when_stdout_is_not_tty`
  - `test_progress_reporter_signature_matches_protocol`
- `tests/unit/test_progress_reporter_nontty.py`:
  - `test_nontty_throttle_emits_every_n_items`
  - `test_nontty_throttle_emits_every_k_seconds`
  - `test_nontty_eta_not_shown_in_first_3_items`
  - `test_nontty_force_emit_on_final_item`
  - `test_nontty_log_line_format_regex` (`r"^\[\w+\] video_id=\S+ N=\d+/total=\d+ elapsed=[\d.]+s ETA=(\d+s|\?)$"`)
- `tests/integration/test_progress_reporter_force_tty.py`:
  - `force_tty=True/False` 각각 instantiation 후 update() 호출 — exception 0.
