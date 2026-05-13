# Contract: services/kb_export.py + cli/transcript.py

**Modules**:
- `src/tube_scout/services/kb_export.py` (신규)
- `src/tube_scout/cli/transcript.py` (신규 — 또는 `project.py` 확장 — Phase 2 task에서 결정)

**Spec FR mapping**: FR-040~FR-042.
**Boundary**: 본 spec 신규. 분석 파이프와 독립.

---

## 함수 시그니처

```python
from pathlib import Path
from typing import Literal

ExportFormat = Literal["txt", "md", "jsonl"]

def export_transcript(
    transcript_json_path: Path,
    output_path: Path,
    *,
    format_: ExportFormat = "txt",
    keep_timestamps: bool = False,
    clean_fillers: bool = False,
    with_meta: bool = False,
    video_meta: VideoMetadata | None = None,  # md/jsonl with_meta=True 시 필수
) -> ExportResult:
    """Export single transcript JSON to operator's KB-ingestible plain text.

    Args:
        transcript_json_path: 01_collect/transcripts/<video_id>.json.
        output_path: 출력 파일 경로 (호출자가 디렉터리 사전 생성).
        format_: txt/md/jsonl.
        keep_timestamps: True 시 [hh:mm:ss] 또는 jsonl start/end 보존.
        clean_fillers: True 시 한국어 ASR 채움 표현 제거 (`음~`, `어~`, `에이`).
        with_meta: md/jsonl 시 영상 메타 헤더 포함.
        video_meta: with_meta=True 시 필수.

    Returns:
        ExportResult — output_path, byte_count, format_, segment_count.

    Raises:
        FileNotFoundError: transcript_json_path 부재.
        ValueError: with_meta=True 인데 video_meta=None.
    """

def export_bulk(
    transcripts_dir: Path,
    output_dir: Path,
    *,
    video_ids: list[str] | None = None,        # None 시 transcripts_dir 전체 스캔
    format_: ExportFormat = "txt",
    keep_timestamps: bool = False,
    clean_fillers: bool = False,
    with_meta: bool = False,
    video_meta_map: dict[str, VideoMetadata] | None = None,
    progress: ProgressReporter | None = None,
) -> BulkExportResult:
    """Export multiple transcripts to a directory. Each video → one output file.

    Output filename: f"{video_id}.{format_}".

    Idempotent: 이미 존재하는 출력은 덮어쓰기 (KB export는 항상 재실행 안전).
    """

class ExportResult(BaseModel):
    output_path: Path
    byte_count: int
    format_: str
    segment_count: int

class BulkExportResult(BaseModel):
    output_dir: Path
    total_videos: int
    exported_count: int
    skipped_count: int
    failed_count: int
    format_: str
```

---

## 형식별 출력 schema (R-13)

### `txt`

세그먼트 텍스트만 줄바꿈 구분. 헤더 없음. 빈 줄 0.

```
안녕하세요 정광석 교수입니다
오늘은 간호연구방법론 8주차 1차시입니다
2022학년도 1학기에 진행되었던
```

`--keep-timestamps`:

```
[00:00:00] 안녕하세요 정광석 교수입니다
[00:00:03] 오늘은 간호연구방법론 8주차 1차시입니다
[00:00:08] 2022학년도 1학기에 진행되었던
```

### `md`

```markdown
# 간호연구세미나 8주차 1차시

- video_id: sUJbkkYzNGc
- duration: 105.0s
- source: ASR (faster-whisper:large-v3:int8_float16)
- privacy_status: unlisted

---

안녕하세요 정광석 교수입니다

오늘은 간호연구방법론 8주차 1차시입니다
```

`--with-meta=False` 시 헤더 생략, 본문만 출력.

### `jsonl`

세그먼트당 한 줄 JSON:

```jsonl
{"start": 0.0, "end": 3.5, "text": "안녕하세요 정광석 교수입니다"}
{"start": 3.5, "end": 8.2, "text": "오늘은 간호연구방법론 8주차 1차시입니다"}
```

`--with-meta=True` 시 첫 줄에 메타 객체 추가:

```jsonl
{"_meta": true, "video_id": "sUJbkkYzNGc", "title": "...", "duration": 105.0, "source": "whisper"}
{"start": 0.0, "end": 3.5, "text": "..."}
```

`--keep-timestamps=False` 시 segment 객체에서 `start`/`end` 제거:

```jsonl
{"text": "..."}
```

---

## Filler 제거 정규식 (`--clean-fillers`)

한국어 ASR에서 빈번한 채움 표현:

```python
_FILLER_PATTERNS = [
    r"\b음+\b",        # 음, 음~, 음음
    r"\b어+\b",
    r"\b에+\b",
    r"\b아+\b",
    r"\b그러니까\b",   # 옵션 — 의미어 손실 위험 있어 신중
    r"\b그래서\b",
    r"\b음[~ㅡ]+\b",
]
```

기본 off — 운영자가 외부 KB 파이프라인에서 자체 정제할 수 있도록. on 시 채움 표현 제거 + 공백 정규화.

---

## UTF-8 + BOM 없음 (FR-040)

```python
output_path.write_text(content, encoding="utf-8")  # BOM 없음 (encoding='utf-8-sig'가 BOM)
```

atomic tempfile + rename 패턴.

---

## CLI 통합

`cli/transcript.py::export` 와 `::export_bulk` 함수가 위 서비스 함수의 thin wrapper. 진행 상황 표시(bulk export only) — ProgressReporter stage `'kb_export'`.

---

## 테스트 진입점

- `tests/contract/test_kb_export_contract.py`:
  - `test_export_signature_matches_contract`
  - `test_export_result_byte_count_matches_file_size`
- `tests/unit/test_kb_export_formats.py`:
  - `test_txt_format_strips_timestamps_by_default`
  - `test_txt_keep_timestamps_includes_brackets`
  - `test_md_with_meta_includes_header`
  - `test_md_without_meta_body_only`
  - `test_jsonl_per_segment_one_line`
  - `test_jsonl_with_meta_first_line_is_meta_object`
  - `test_clean_fillers_removes_korean_filler_patterns`
  - `test_output_utf8_no_bom`
- `tests/integration/test_kb_export_bulk.py`:
  - 50개 transcripts → output_dir에 50 파일 생성 검증.
  - 같은 video_id의 ASR과 API caption 출처 모두 동일 export 산출(format-agnostic).
