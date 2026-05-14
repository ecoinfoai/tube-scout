# Cross-Spec Boundary Regression — Phase 5 Pre-Removal Gate (T100)

Date: 2026-05-14
Branch: 013-takeout-local-asr-reuse
Phase: 5 (US3) pre-removal — yt-dlp surface still present
DB schema: v4 (spec 013)
Constitution VII gate: prior-spec consumers MUST keep passing on v4 DB.

## Scope

Spec 013 FR-046 deletes spec 012 (yt-dlp adapter). Before that deletion
runs (T089-T094), this measurement captures the regression baseline —
all integration tests that exercise prior-spec schema consumers AND the
spec 012 endpoints that will be removed. The "after" snapshot is to be
captured in T095 by dev1 after deletion.

## Note on T100 description

`tasks.md T100` names `tests/integration/test_v3_to_v4_idempotent.py`
which does not exist in the tree. The equivalent v4 migration
idempotency check lives in `tests/integration/test_v4_migration.py`
(+ `test_v4_auto_ensure.py` for auto-ensure path). Substituting these
files for the named one is faithful to the intent of T100 (idempotent
v3 → v4 upgrade verification).

## Suite A — v4 DB schema consumers (spec 007 / 010 / 011 boundary)

```
uv run --extra dev python -m pytest \
  tests/integration/test_v4_migration.py \
  tests/integration/test_boundary_spec_010_compat.py \
  tests/integration/test_boundary_spec_011_db.py \
  tests/integration/test_cross_spec_boundary.py \
  -q
```

Result: **22 passed in 1.16s**

| file | passed | failed | skipped |
|---|---|---|---|
| test_v4_migration.py | included | 0 | 0 |
| test_boundary_spec_010_compat.py | included | 0 | 0 |
| test_boundary_spec_011_db.py | included | 0 | 0 |
| test_cross_spec_boundary.py | included | 0 | 0 |
| **TOTAL** | **22** | **0** | **0** |

## Suite B — spec 012 pre-removal endpoints

These tests will be deleted alongside the yt-dlp adapter in T089-T094.
Captured here as the last known-good baseline so that any cleanup
oversight (e.g. dangling import in `services/audio_fingerprint.py`,
left-behind audit_writer fieldnames) shows up as a failure delta
rather than a silent removal.

```
uv run --extra dev python -m pytest \
  tests/integration/test_audio_fingerprint_flow.py \
  tests/integration/test_audio_fp_hamming_distribution.py \
  tests/integration/test_audit_csv_compliance.py \
  tests/integration/test_collect_audio_all_channels_e2e.py \
  tests/integration/test_collect_audio_project_dir_option.py \
  tests/integration/test_collect_chain.py \
  tests/integration/test_dispatch_audio_fingerprint.py \
  tests/integration/test_dispatch_audio_fingerprint_no_mock.py \
  tests/integration/test_dispatch_ytdlp_transcripts_e2e.py \
  tests/integration/test_ytdlp_caption_flow.py \
  tests/integration/test_ytdlp_rate_limit.py \
  -q
```

Result: **31 passed, 3 skipped in 1.37s**

| file | passed | failed | skipped |
|---|---|---|---|
| test_audio_fingerprint_flow.py | included | 0 | included |
| test_audio_fp_hamming_distribution.py | included | 0 | included |
| test_audit_csv_compliance.py | included | 0 | included |
| test_collect_audio_*.py | included | 0 | 0 |
| test_collect_chain.py | included | 0 | 0 |
| test_dispatch_audio_fingerprint*.py | included | 0 | 0 |
| test_dispatch_ytdlp_transcripts_e2e.py | included | 0 | 0 |
| test_ytdlp_caption_flow.py | included | 0 | 0 |
| test_ytdlp_rate_limit.py | included | 0 | 0 |
| **TOTAL** | **31** | **0** | **3** |

The 3 skipped cases are env-gated (chromaprint binary / network) and
are not regressions; they are documented as skipped in their own files.

## Combined gate

| suite | passed | failed | skipped |
|---|---|---|---|
| A (prior-spec boundary on v4) | 22 | 0 | 0 |
| B (spec 012 pre-removal) | 31 | 0 | 3 |
| **TOTAL** | **53** | **0** | **3** |

**Phase 5 entry condition (Constitution VII regression gate) — PASS.**

## What dev1 must compare in T095

After T089-T094 runs, dev1 should re-execute Suite A above (Suite B
files will have been deleted) and confirm:

1. Suite A delta = 0 failed, 0 newly skipped (only intentional spec 012
   tests vanish).
2. `test_us3_no_ytdlp_grep.py` flips from 12 failed → 0 failed.
3. `test_phase4_legacy_removal.py` flips from 5 failed → 0 failed.

If any Suite A test newly fails, T089-T094 introduced a cross-spec
regression — revert the offending deletion and route through pp1.

## Audit trail

- Commit baseline: HEAD = `2b363b7` (post-T088/T102 commits).
- Pre-removal capture performed by adv1.
- Post-removal capture deferred to dev1 (T095).
