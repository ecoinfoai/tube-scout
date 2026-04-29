# Tube Scout v6 — Cross-Spec Consistency & Integration Fix

## Background

tube-scout has accumulated specs 001 → 002 → 003 → 004 → 005 → 006 → 007 → 008
(seven feature increments, all merged into master at v0.3.0). Each spec was
designed and implemented well in isolation, but the seams between them were
not enforced — the integration boundaries between specs drifted, and the user
experience for the operator (who has to use the CLI end-to-end) is broken in
multiple places.

This idea exists to capture every concrete consistency / integration defect
found during the first real-world usage attempt on 2026-04-29 and to propose
a unified fix.

## Problem (concrete defects discovered, 2026-04-29)

### D-1. Output directory fragmentation (5 conventions across 5 commands)

| Command | Looks at |
|---------|---------|
| `tube-scout collect videos` | `projects/{ts}/01_collect/channels/{channel_id}/...` |
| `tube-scout search` | `output/latest/parsed/.../parsed_titles.json` (OutputManager symlink) |
| `tube-scout validate` | `output/latest/parsed/{channel}/parsed_titles.json` |
| `tube-scout content fingerprint` | `projects/{ts}/02_analyze/channels/{channel_id}/parsed_titles.json` |
| `tube-scout init` (and single-channel fallback) | `data/raw/...` |

Five different conventions across five commands all expecting different
paths. End result: a fresh user runs `collect videos` → sees 216 videos
collected → `search` returns 0 because it looks at a different directory.

### D-2. `parsed_titles.json` is never generated automatically

`services/title_parser.py` exposes `TitleParser`, but **no CLI command
invokes it**. Every downstream command that needs `parsed_titles.json`
(`search`, `validate`, `content fingerprint`, `report content`, `bundle_report`)
silently returns 0 results because the file does not exist.

A user has to run a Python REPL workaround to call `TitleParser.parse_batch()`
+ `save_results()` and place the JSON into the (multiple, incompatible)
locations expected by each command.

### D-3. `projects/latest` symlink update is unreliable

The symlink `projects/latest` was pointing to an empty project
(`projects/20260429-141145`) while the actual data was in
`projects/20260429-135552`. Some command must have created an empty project
and updated `latest` without ever filling it. Result: every `--project latest`
command reports "No videos found".

### D-4. Secret-environment-variable name mismatch

| What is provided (agenix) | What the code expects |
|---|---|
| `TUBE_SCOUT_CLIENT_SECRET_B64` (base64-encoded JSON) | `TUBE_SCOUT_CLIENT_SECRET` (filesystem path) |

`tube-scout auth --channel <alias>` fails with `TUBE_SCOUT_CLIENT_SECRET
environment variable is required. Set it to the path of your OAuth client
secret JSON file.` even though the same JSON exists in `_B64` form.

The code should accept either form (and decode the `_B64` automatically) or
the agenix-side convention should match the code-side expectation. Today
neither side adapts and the user has to do a manual `base64 -d > file +
export`.

### D-5. `channel_id` vs `alias` is split across commands inconsistently

| Command | Identifier accepted |
|---------|---------------------|
| `data/config.json` (`init`) | `channel_id` only (no alias) |
| `tokens/{alias}_token.json` | alias |
| `auth --list` | alias |
| `search --channel <alias>` | alias |
| `collect videos` | `channel_id` (from `data/config.json`) |
| `content scan --channel <alias>` | alias |

There is no single source of truth that maps alias ↔ channel_id, so the
operator must mentally hold the mapping and switch between the two depending
on which command they run.

### D-6. CLI version was hardcoded (already fixed)

`cli/main.py` had `0.1.0` hardcoded in `_version_callback`. T107 of spec 008
bumped `pyproject.toml` to `0.3.0` but missed this literal. Fixed in commit
`106c32d` by switching to `importlib.metadata.version()`. Other hardcoded
constants (e.g. paths, format strings) likely have similar latent regressions.

### D-7. spec 007 lived on a feature branch unmerged for 22 days

`007-content-reuse-detection` was completed on 2026-04-07 (10 commits, 1452
tests passing) but was never merged into master. The orchestrator's memory
even labeled it "미구현" (unimplemented). Spec 008 (admin web UI) was built
on top of master without spec 007 → 008's pipeline.py reuse_detection stage
landed as a stub. Merge happened on 2026-04-29 with conflicts (CLAUDE.md,
pyproject.toml).

There was no merge-discipline policy — completing a spec on a feature branch
and not merging is treated as "done" by some artifacts and "not done" by
others.

### D-8. force-ssl OAuth scope is required but not auto-prompted

memory `project_caption_survey` records: 비공개 자막 88.6%, ASR 99.4%,
**force-ssl scope 필요**. Yet `auth --channel <alias>` does not request the
force-ssl scope by default, and there is no detection / re-auth prompt when
`Captions API fallback unavailable: invalid_scope` fires. Users have to
manually `auth --revoke` and re-authenticate, hoping the consent screen
includes the captions permission.

### D-9. `tests/manual/` runs in the default test suite

`pytest tests/` produces `1710 passed, 3 errors`. The 3 errors are all in
`tests/manual/` (OAuth-required tests that need real credentials). Manual
tests should be excluded by a default pytest marker or path so the default
run is clean.

### D-10. Error messages don't tell the operator what to do

Examples:

- `Captions API fallback unavailable: invalid_scope: Bad Request` → no
  guidance like "run `tube-scout auth --channel <alias> --scope captions`".
- `No videos found. Run 'tube-scout collect videos' first.` → run after a
  successful collect because the symlink is stale.
- `No videos found for channel 'default' matching the given criteria.` →
  user provided no `--channel`; tool defaults to `'default'` instead of
  prompting or reading a recently-used alias.

### D-11. README / docs gloss over the necessary setup details

Docs are now in English (good), but the README does not enumerate:

- which env vars must be set (and in which form),
- alias-vs-channel-id distinction,
- the `output/` vs `projects/` split,
- force-ssl re-auth procedure,
- how to bootstrap `parsed_titles.json` end-to-end.

A new operator will hit each of D-1 through D-10 inside the first hour of
use.

### D-12. Spec 008 web UI inherits every defect above

The web UI's `_collect_all_for_web` helper (T035-bis) imports `cli/collect.py`
internals. Whatever symlink / parsed-titles / scope / env-var bug exists in
the CLI also breaks the web UI. The system-test that the web UI's pipeline
ever produces a real reuse-detection report against real channel data has
not been run.

## Desired Outcome

A new operator who runs `nix develop` for the first time should be able to:

1. Set one secret (agenix) and one alias (`tube-scout admin add-department`).
2. Run **one** command (e.g. `tube-scout scan --channel <alias>
   --professor "홍길동" --course "인체구조와기능"`) that performs:
   collect videos → parse titles → collect transcripts (force-ssl auto) →
   fingerprint → compare → quality → report,
   without manually creating directories, decoding secrets, or invoking
   Python REPL.
3. Find the result in **one** place (`projects/{ts}/03_report/...` or
   identical path used by every command).
4. Get clear, actionable error messages whenever a precondition is not met.

## Constraints

- Do not break any existing CLI command's surface contract (spec 008 web UI
  imports them; dev-squad tests rely on them).
- Single source of truth for the alias↔channel_id↔token mapping (probably
  consolidate around alias).
- Single output convention. Probably `projects/{ts}/...` everywhere; deprecate
  `output/` and `data/raw/` after a migration tool exports them.
- Keep agenix-managed secret access — do not require any plaintext file in
  the repo or project tree. The CLI should accept `_B64` form natively or
  decode-on-load to a tmpfs path.
- Failures must explain themselves: every error path includes the next
  command the operator should run.

## Success Criteria

- SC-1: Fresh-environment quickstart from `nix develop` to a content-reuse
  report in **one terminal session** with no Python REPL workarounds.
- SC-2: Every CLI command with a `--channel` flag accepts an alias only —
  channel_id is internal.
- SC-3: All result artifacts land under a single root (`projects/{ts}/`) and
  every reader command finds them via `--project latest` or by default.
- SC-4: `parsed_titles.json` is generated automatically (either at the end of
  `collect videos` or via an explicit `analyze parse-titles` command) — every
  downstream command never sees "missing parsed_titles" silently.
- SC-5: Force-ssl scope is requested by default during `auth --channel`. If
  an existing token lacks the scope, the operator gets a clear "re-auth"
  prompt rather than `invalid_scope`.
- SC-6: `_B64` and file-path forms of `TUBE_SCOUT_CLIENT_SECRET` both work
  out of the box.
- SC-7: `tests/manual/` is excluded from the default `pytest tests/` run.
- SC-8: The web UI (spec 008) — running with one registered alias — produces
  a working content-reuse report end-to-end without any of the workarounds
  above.

## Open Questions

- [NEEDS CLARIFICATION: migration of existing `output/` and `data/raw/`
  artifacts. Do we deprecate hard, or write a one-time migration command?]
- [NEEDS CLARIFICATION: should `init` be deprecated entirely in favor of
  `admin add-department` (alias-first) since alias is the long-term identifier?]
- [NEEDS CLARIFICATION: TitleParser success rate is 31% on Bu-San Health Univ
  Nursing channel titles — does the regex-pattern set need expansion, or do
  we accept fallback parsing as sufficient?]

## Discussion Notes

> This is the first idea that targets cross-spec quality rather than a new
> capability. It is the natural conclusion of running through specs 001–008
> in real-world conditions — every increment was internally consistent but
> the seams compounded. The fix is about subtraction (one output convention,
> one identifier, one entry point) rather than addition.

> Estimated work: 1 dev-squad cycle (1–2 days) for the consolidation +
> migration tool. Bigger than a spec-008-style web layer but smaller than a
> new analytical capability. The dev-squad team that just shipped 008 has
> the context.

> Real-world usage that triggered this idea: trying to run
> "collect transcripts for 홍길동 / 인체구조와기능 across multiple academic
> years and compare them for re-use" — a use case that *should* be the
> headline scenario for tube-scout, but currently requires hand-editing
> directories, manually invoking TitleParser via Python REPL, decoding base64
> secrets, fixing symlinks, and re-authenticating with the right scope.
