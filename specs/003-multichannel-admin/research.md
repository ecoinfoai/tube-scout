# Research: Multi-Channel Administration

**Date**: 2026-04-04

## R1: Multi-Channel Token Storage Architecture

**Decision**: Store tokens as `{alias}.json` files under `~/.config/tube-scout/tokens/`, with a `channels.json` registry mapping alias → channel_id + metadata.

**Rationale**: File-per-channel is simpler than a single DB file, enables agenix encryption per-file, and avoids corruption propagation (one corrupt token doesn't affect others). The registry file provides O(1) lookup without scanning the directory.

**Registry format**:
```json
{
  "간호학과": {
    "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
    "channel_name": "부산보건대 간호학과",
    "registered_at": "2026-04-04T12:00:00",
    "last_used_at": "2026-04-04T15:30:00"
  }
}
```

**Token resolution**: On `--channel 간호학과`, read `channels.json` → get channel_id → load `tokens/간호학과.json` → authenticate.

**Alternatives Considered**:
- SQLite database — rejected: overkill for 5-30 channels, harder to encrypt with agenix.
- Single tokens.json with all tokens — rejected: one corrupt entry affects all channels.

## R2: Video Title Parsing Strategy

**Decision**: Universal regex-based parser with priority-ordered pattern list. Patterns are tried top-to-bottom; first match wins.

**Rationale**: Korean university lecture titles follow 4-5 common patterns. A priority list covers 85%+ of titles without per-department configuration. New patterns are added to the list as discovered.

**Pattern priority**:
1. `{교수} {연도} {학과} {교과목} {N}주차 {M}차시` — 가장 표준적
2. `{교과목} {연도} {N}학기 {교수} {N}주차 {M}차시` — 학기 명시
3. `{연도}-{학기}/{연도}-{학기} {교수}/{교수} {교과목} {N}주차 {M}차시 ({학과})` — 공동강의
4. `{연도}학년도 {N}학기 {교과목} {N}주차 ({교수})` — 학년도 형식
5. `{번호}.{교수} {교과목} {N}주차 {M}차시({학과})` — 번호 접두사

**Fallback**: 정규식 매칭 실패 시, 개별 필드 추출 시도 (주차만이라도, 교수명만이라도). 완전 실패 시 `parse_error=True`.

**Alternatives Considered**:
- LLM-based parsing — rejected: 5,000 titles × LLM call = 비용/시간 과다. 정규식으로 85%+ 커버 가능.
- NER (Named Entity Recognition) — considered for professor name extraction fallback, but Korean NER models have limited accuracy for person names in mixed-format titles.

## R3: YAML Search Configuration

**Decision**: Use PyYAML for parsing. Search config supports `filters` (AND), `queries` (OR list), and `exclude` sections.

**Rationale**: YAML is human-readable, already familiar in CLI tools. The three-section structure covers simple (single filter), complex (OR queries), and exclusion scenarios.

**Execution logic**:
1. Parse YAML into SearchFilter/SearchQuery models (Pydantic validated)
2. Apply `filters` as AND conditions
3. If `queries` present, apply each query group and union results
4. Apply `exclude` to final result set
5. Return deduplicated list

**Alternatives Considered**:
- JSON config — rejected: less readable for manual editing.
- SQL-like query syntax — rejected: too complex for target users (academic affairs staff).

## R4: Department Report Generation

**Decision**: Use Jinja2 for HTML, openpyxl for Excel, and weasyprint (optional) for PDF. HTML is the primary format with plotly for interactive charts.

**Rationale**: Jinja2 + plotly already in v1/v2 stack. openpyxl is the standard Python library for Excel generation. weasyprint converts HTML→PDF but requires system-level dependencies; PDF is optional (HTML+Excel minimum).

**Report structure** (Excel sheets):
1. **개요** — department overview metrics
2. **교수별 상세** — per-professor detail table
3. **준수율** — compliance analysis with conditional formatting
4. **이상 탐지** — validation findings by severity

**Alternatives Considered**:
- pandas ExcelWriter — rejected: openpyxl gives more control over formatting, conditional formatting, charts.
- ReportLab for PDF — rejected: weasyprint is simpler (HTML→PDF), and PDF is optional.

## R5: Title Validation Rules Engine

**Decision**: Rule-based engine with each V-rule as an independent function. Rules receive parsed titles + video metadata and return ValidationFinding objects.

**Rationale**: Independent rule functions are testable in isolation, easy to add new rules, and can be run selectively. Each rule maps to one validation ID (V-001 to V-009).

**Rule execution**:
```python
rules = [check_year_mismatch, check_duplicates, check_invalid_week, ...]
findings = []
for rule in rules:
    findings.extend(rule(parsed_titles, videos, calendar))
```

**Edit distance for V-004**: Use `python-Levenshtein` (C extension, fast) for professor name comparison. Group names with distance ≤ 2, flag as potential inconsistency.

**Alternatives Considered**:
- ML-based anomaly detection — rejected: overkill for well-defined rules, harder to explain false positives.
- Single monolithic validator — rejected: harder to test, harder to add rules.

## R6: Timestamped Output Management

**Decision**: `OutputManager` class creates `./output/report-YYYYMMDD-HHMM/` directories. Maintains `latest` symlink. Thread-safe via directory creation with `exist_ok`.

**Rationale**: Timestamp-based naming prevents collisions (1-minute granularity sufficient for single-user CLI). Symlink provides stable path for scripts that reference the latest output.

**Alternatives Considered**:
- Sequential numbering (report-001, report-002) — rejected: requires scanning directory for next number, less informative than timestamp.
- Git-based versioning — rejected: output data can be large (transcripts, Parquet), not appropriate for git.

## R7: Supplementary Video Classification

**Decision**: Detect supplementary videos by keyword matching in titles: "핵심영상", "보완영상", "질문응답", "보충", "특강", "OT". Classify as `category="supplementary"` in ParsedTitle.

**Rationale**: These are not regular lecture sessions and should not be counted in weekly coverage or session completeness metrics. They should appear in reports but in a separate section.

**Alternatives Considered**:
- Manual tagging by admin — rejected: too labor-intensive for 5,000+ videos.
- Duration-based classification (< 5 min = supplementary) — rejected: short lecture summaries are legitimate regular content.
