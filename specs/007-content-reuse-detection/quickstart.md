# Quickstart: Content Reuse Detection

## Prerequisites

1. tube-scout installed and configured
2. Channel registered via `tube-scout auth register --channel <alias>`
3. OAuth re-authentication with force-ssl scope (one-time after upgrade)
4. Metadata and title parsing completed: `tube-scout collect all --channel <alias>`

## Initial Setup (One-time)

```bash
# 1. Collect all captions (public + private)
#    Public: instant. Private: limited by daily API quota (~40/day).
#    Resume-safe: re-run next day if quota runs out.
tube-scout collect transcripts --channel dept-nursing-science

# 2. Run full analysis pipeline
tube-scout content scan --channel dept-nursing-science \
  --year-from 2025 --year-to 2026
```

## Periodic Workflow (Monthly/Semester)

```bash
# 1. Collect new videos only (incremental)
tube-scout collect transcripts --channel dept-nursing-science

# 2. Re-run analysis
tube-scout content scan --channel dept-nursing-science \
  --year-from 2025 --year-to 2026

# 3. Generate report
tube-scout report content --channel dept-nursing-science \
  --format xlsx --year 2026 --semester 1

# 4. Review flagged videos (🔴 critical first)
tube-scout content review --channel dept-nursing-science \
  --status UNREVIEWED --grade critical

# 5. Mark reviewed items
tube-scout content review --channel dept-nursing-science \
  --mark 42 CONFIRMED_DUPLICATE
tube-scout content review --channel dept-nursing-science \
  --mark 57 FALSE_POSITIVE
```

## Key Commands

| Command | Purpose |
|---------|---------|
| `collect transcripts` | Collect captions (public + private) |
| `content fingerprint` | Generate hashes + embeddings |
| `content compare` | Compare pairs, calculate suspicion scores |
| `content quality` | Run Q-001~Q-005 quality checks |
| `content review` | View/update review status |
| `content scan` | Full pipeline (fingerprint→compare→quality) |
| `report content` | Generate HTML/Excel/JSON report |

## Understanding Results

### Suspicion Grades

| Grade | Score | Action |
|-------|-------|--------|
| 🔴 Critical | 80-100 | Review immediately |
| 🟠 High | 60-79 | Review this week |
| 🟡 Moderate | 40-59 | May be partial update |
| 🟢 Normal | 0-39 | New content |

### Review Statuses

| Status | Meaning |
|--------|---------|
| UNREVIEWED | Auto-analyzed, not yet checked by admin |
| CONFIRMED_DUPLICATE | Admin confirmed: reused video |
| FALSE_POSITIVE | Admin confirmed: legitimate new content |
