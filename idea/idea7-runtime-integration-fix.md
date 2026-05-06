# Tube Scout v7 — Runtime Integration & Multi-Channel Auth Fix

## Background

idea6 (Phase 4 closure 2026-04-30) addressed cross-spec consistency at the
**filesystem / configuration boundary**: alias-aware ProjectManager, atomic
`commit_latest`, secret loader `_B64`+path, force-ssl scope verify, silent-skip
elimination, headless TTY guard, etc. spec 001~008 + idea6 all merged at
v0.3.0.

This idea (idea7) captures defects discovered during the **first end-to-end
real-data run with the post-idea6 code** on 2026-05-07 by the operator. The
run exercised the full pipeline:

```
auth → collect videos → collect transcripts → collect retention → ...
```

`auth` and `collect videos` succeeded. `collect transcripts` succeeded after
adding `--project latest` (and produced 52/216 captions, but that is its own
audit item). `collect retention` was completely blocked by an OAuth scope
mismatch and a hung callback. The pipeline cannot reach `content scan` or
`report bundle` until the items below are fixed.

idea6 fixed the **persistent state** layer; idea7 fixes the **runtime invocation
+ auth flow** layer.

## Problem (concrete defects discovered, 2026-05-07)

### D-13. `--project` default creates a fresh empty project on every command

`cli/project.py:resolve_project(project=None)` calls `mgr.create_project()`,
producing a brand-new timestamped project directory. This is correct for
`collect videos` (a fresh data run), but every subsequent command (`collect
transcripts`, `collect retention`, `collect comments`, `collect analytics`,
`content fingerprint`, `report bundle`, ...) also defaults to `project=None`
and therefore **creates a new empty project of its own** and looks for
`videos_meta.json` inside it — guaranteed to be absent.

Symptom seen by the operator:

```
$ tube-scout collect transcripts --channel nursing
No videos found. Run 'tube-scout collect videos' first.
```

— even though `collect videos` had succeeded one command earlier and the JSON
was sitting in `projects/20260506-151907/01_collect/...`. Two empty
spam-projects (`20260506-152548`, `20260506-152611`) were created within
seconds of each other simply by re-running `collect transcripts` twice.

idea6 D-1 alias-aware paths solved part of this, but the per-command
**default** of `create_project()` re-introduces the same fragmentation by
creating empty siblings.

**Required behavior**: every command except `collect videos` (or whichever is
designated as "starts a new run") must default to `--project latest`.
Alternatively, `resolve_project(project=None)` should *open existing latest*
and only fall back to `create_project()` if no latest exists or the operator
opts in via `--new-project`.

### D-3-residual. `latest` symlink is not auto-updated by `collect videos`

After `tube-scout collect videos --channel nursing` produced
`projects/20260506-151907/01_collect/.../videos_meta.json` with 216 videos,
`projects/latest` continued to point at `20260429-135552` (a 8-day-old empty
project). The operator had to run `ln -sfn 20260506-151907 projects/latest`
manually before any downstream command could see the new data.

idea6 added `ProjectManager.commit_latest` (atomic + empty-project guard,
commit `51a0bc0`), but **`collect videos` does not call it**. The fix is
incomplete: D-3 was closed at the `ProjectManager` layer but never wired into
the actual collect pipeline. Any other producer command (e.g. `content
fingerprint` if it stages a new project) likely has the same gap.

### D-14. `collect retention` and `collect analytics` lack `--channel`

```
$ tube-scout collect retention --channel nursing --project latest
No such option: --channel
```

While `collect videos`, `collect transcripts`, `collect comments` all accept
`--channel <alias>`, `collect retention` and `collect analytics` (and
presumably `collect bulk`) do not. This is asymmetric API surface inside the
same command group, contradicting idea6 ADR-001 (alias-aware API).

### D-15. `collect retention/analytics` ignores multi-channel tokens entirely

Tracing through `cli/collect.py:collect_retention_command` (line 223+) →
`services/auth.py:build_analytics_client()` (line 231) →
`services/auth.py:authenticate()` (line 172) → `_token_path()` (line 149) =
`~/.config/tube-scout/token.json`.

That is the **default single-channel** token path. `tokens/<alias>.json` (the
multi-channel registry produced by `auth --channel`) is never consulted by
the retention/analytics path.

Consequence on the operator's machine:

- `~/.config/tube-scout/tokens/nursing.json` exists with both
  `youtube.force-ssl` and `yt-analytics.readonly` scopes, registered fresh
  on 2026-05-06 23:59 KST.
- `~/.config/tube-scout/token.json` is left over from 2026-04-29, holding
  only `youtube.force-ssl` (single-scope era).
- `collect retention` reaches for `token.json`, tries to refresh with the
  current `SCOPES = [force-ssl, yt-analytics]` set, and Google rejects with
  `invalid_scope: Bad Request` because the original consent did not cover
  `yt-analytics.readonly`.

This is a **critical blocker** — the operator cannot collect retention
without first deleting the legacy default token and going through OAuth
again, while the correct multi-channel token is sitting unused next to it.

### D-16. Two parallel token systems coexist

`token.json` (single-channel default), `token_forcessl.json` (an even older
force-ssl variant from 2026-04-07), and `tokens/<alias>.json` + `channels.json`
(multi-channel registry, idea6) all live under `~/.config/tube-scout/`. The
code branches based on which command and which code path picked which
function. This dual system is the root cause of D-15 and will keep surfacing
fresh defects until unified.

**Required behavior**: deprecate `token.json` / `token_forcessl.json`. Every
command that needs auth must take `--channel <alias>` (or pick the registered
default if exactly one alias exists) and route through
`authenticate_channel(alias)`. Migrate any legacy `token.json` content to
`tokens/<alias>.json` on first run.

### D-17. OAuth callback hangs in multi-account browser environments

`flow.run_local_server(port=8080)` opens the consent page and waits for the
browser to be redirected back to `http://localhost:8080/?code=...`. On the
operator's machine (Brave with multiple Google accounts logged in,
`authuser=5` in the URL fragment), the consent page completed server-side
but the browser never redirected to localhost:8080 — the page stayed at
`accounts.google.com/.../consent#`. CLI sat on `LISTEN 127.0.0.1:8080`
forever; user had to `kill <pid>`.

This is intermittent (depends on browser, account slot, Brave state,
Chromium-family redirect interception) and there is no recovery path. The
CLI must:

1. Default to **`out-of-band` / device-code flow** (`urn:ietf:wg:oauth:2.0:oob`
   or the newer headless device flow) so the user copies a code into the
   terminal — independent of browser redirect behavior.
2. Or at minimum print a **"paste the redirect URL here"** prompt so the
   operator can rescue a stuck consent without killing the process.
3. Or print explicit guidance after N seconds of no callback ("Browser
   redirect did not arrive in 60s — kill this command, set BROWSER, retry").

### L-1. Captions API fallback emits the youtube-transcript-api stack trace verbatim

For each private video, `collect transcripts` first tries
`youtube-transcript-api`, fails with a multi-line "This video is private"
exception, then succeeds via Captions API. The 1st-step exception is
printed in full (≈10 lines per private video), drowning the actual progress
output.

**Required behavior**: dim or one-line summary for the 1st-step failure
when the 2nd step succeeds. Only show the full exception when both fail.

### L-2. `transcripts/*.json` does not record which source produced it

```python
$ python -c "import json; print(json.load(open(...)).get('source'))"
None
```

The transcript JSON omits a `source` field, so the operator cannot tell
post-hoc which captions came from `youtube-transcript-api (manual)`,
`(auto_generated)`, or Captions API fallback `(captions_api)`. The CLI
*prints* this distinction during collection but does not persist it.

This breaks any audit that asks "how many of our captions are ASR?" or
"which captions need a human review pass?".

**Required behavior**: persist `source: manual | auto_generated | captions_api`
in every transcript JSON. Backfill possible from existing files only via
re-collection, so this fix becomes load-bearing for downstream content
quality reports.

### L-3. No audit for "transcript missing — why?"

Real-data run produced **52/216 (24%) captions** while the channel survey
estimated 99.4% ASR availability. The 164 misses are not classified —
they could be: ASR not generated by YouTube, age-restricted, deleted,
member-only, owner-disabled captions, code rate-limit exhaustion,
Captions API quota, or a code defect.

There is no `tube-scout collect transcripts --report-missing` mode that
emits a CSV of `(video_id, title, status, error_class, hint)` per missed
video. Without that, idea3.1's "completeness" claim has no data backing.

**Required behavior**: failure-classifying audit pass that produces a
diagnostic report, surfaced in `report bundle` and the admin web UI.

## Desired Outcome

A second-time operator (the same person, returning a week later) can run:

```bash
tube-scout collect all --channel nursing
```

and have:

1. Every collect step (videos, transcripts, retention, comments, analytics,
   bulk) routed through the **same** multi-channel token (`tokens/nursing.json`),
   with no `token.json` fallback.
2. Each step writing into the **single** project created by the first step,
   with `projects/latest` automatically pointing at it the moment data lands.
3. No empty sibling projects. No symlink rescue. No `--project latest` opt-in.
4. If OAuth must run, a device-code flow that is independent of browser state.
5. A diagnostic transcript-miss report alongside the captions, so the operator
   knows why 164/216 captions were missed before they file a bug.

The full chain `collect all → content scan → report bundle (PDF)` must
complete on the operator's machine without manual intervention between steps.

## Constraints

- Backward compatibility for `--project <explicit>` and `--project latest` —
  these explicit forms must keep working unchanged. The change is the
  default for `project=None`.
- Migration of legacy `token.json` to `tokens/<alias>.json` must be
  automatic on first run — no manual `auth --revoke` ritual.
- Device-code OAuth flow should be the default, with `--browser-redirect`
  as an opt-in for environments that prefer it.
- All changes must keep idea6's invariants (alias-aware paths, atomic
  commit_latest, headless TTY guard, silent-skip lint).

## Success Criteria

- SC-1: `tube-scout collect transcripts --channel nursing` (no `--project`)
  finds the videos that the previous `collect videos` collected, with no
  empty sibling project created.
- SC-2: `tube-scout collect videos --channel nursing` updates
  `projects/latest` symlink atomically once the data lands.
- SC-3: `tube-scout collect retention --channel nursing` accepts the option
  and uses `tokens/nursing.json` (not `token.json`).
- SC-4: Running `collect retention` on a system that has a stale legacy
  `token.json` with insufficient scopes does **not** fail — it routes
  through the multi-channel token instead.
- SC-5: OAuth flow can complete without a browser redirect — operator
  copies a device code or pastes the redirect URL.
- SC-6: Captions API fallback prints ≤2 lines per private video (not the
  full youtube-transcript-api exception).
- SC-7: Every transcript JSON includes a `source` field.
- SC-8: `tube-scout collect transcripts` produces a `transcripts_audit.csv`
  classifying every missed video by failure reason.
- SC-9: `tube-scout collect all --channel nursing` followed by `content
  scan` and `report bundle --format pdf` completes on the operator's
  machine with no `--project` flag and no manual symlink fix.

## Decisions

(Confirmed by operator on 2026-05-07.)

### DEC-1. Legacy `token.json` is auto-migrated to `tokens/<alias>.json`

On first multi-channel-aware invocation:

1. Read `~/.config/tube-scout/token.json` (and `token_forcessl.json` if
   present) — extract `channel_id` from the credentials.
2. Look up `channels.json` registry for an alias whose `channel_id`
   matches.
3. **Match found**: move the legacy token to `tokens/<alias>.json`
   (atomic rename, 0600). If `tokens/<alias>.json` already exists, keep
   the file with the newer mtime and discard the older.
4. **No match**: delete the legacy file and emit guidance:
   `Run 'tube-scout auth --channel <name>' to register this channel.`

Rationale: forces unification (resolves D-16) without strand the operator
in a re-auth ritual when the existing refresh token is still valid. After
migration, no code path reads `token.json` — `authenticate_channel(alias)`
becomes the single entry point.

### DEC-2. OAuth default = device-code; `--browser-redirect` is opt-in

Default flow (`auth --channel <alias>`, or implicit re-auth from any
collect command):

1. Print a verification URL + 8-character device code to the terminal.
2. Operator opens the URL in any browser (already logged in as the
   channel owner) and enters the code.
3. CLI polls Google's token endpoint until consent or timeout.

Opt-in `--browser-redirect`:

- Operator passes `--browser-redirect` when they prefer the legacy
  `flow.run_local_server(port=8080)` redirect — appropriate for single-
  account environments without redirect interception.
- Headless detection (idea6 B7 TTY guard) **forces device-code** even if
  `--browser-redirect` is requested, to prevent silent hangs in
  systemd/SSH contexts.

Rationale: the operator was blocked today (2026-05-07) by exactly the
multi-account Brave / `authuser=5` redirect failure that device-code is
designed to bypass. Browser-redirect remains available for cases where
it works one-shot, but it is no longer the default.

### DEC-3. Channel resolution: single = auto, multiple = require `--channel`

When any command needing channel-bound auth (`collect retention`,
`collect analytics`, etc.) is invoked **without** `--channel`:

| Registry state | Behavior |
|---|---|
| 0 aliases | Refuse + emit `Run 'tube-scout auth --channel <name>' first.` |
| 1 alias | Auto-select with a dim notice: `Using channel: <alias> (only registered alias)`. |
| 2+ aliases | Refuse + list aliases (with channel_id + last-used date) + show the corrected command. |

A future `--all-channels` flag for batch operations is **out of scope for
idea7**. Operators who need all-channel runs must script the loop
externally for now.

Rationale: prompts break automation (cron, web UI, CI). Auto-running on
all aliases risks unintended quota burn and processing of wrong channels.
Single-auto + multi-explicit is predictable, automation-friendly, and
prevents silent mistakes.

## Discussion Notes

> idea7 was discovered during the first real end-to-end run on 2026-05-07,
> one week after idea6 Phase 4 closure. idea6 fixed the *static* boundaries
> (paths, env vars, scopes, silent-skip); idea7 fixes the *runtime*
> boundaries (project resolution defaults, multi-channel token routing,
> OAuth callback robustness, transcript metadata).
>
> Priority ordering by blast radius:
> - **Critical (blocks today's pipeline)**: D-15 (multi-channel token
>   ignored by retention/analytics), D-17 (OAuth hang).
> - **High (every operator hits these on day 1)**: D-13 (`--project` default
>   creates empty project), D-3-residual (`latest` not auto-updated),
>   D-14 (asymmetric `--channel` support).
> - **Medium**: D-16 (token system unification — the root of D-15).
> - **Low (polish)**: L-1 (verbose stack trace), L-2 (missing `source`),
>   L-3 (no transcript-miss audit).
>
> Recommend bundling all of the above into a single spec rather than
> piecemeal commits — they are tightly coupled around the same
> auth/project resolution paths and a partial fix would re-introduce the
> "fix in one place, regression in another" failure mode that produced
> idea6 in the first place.
