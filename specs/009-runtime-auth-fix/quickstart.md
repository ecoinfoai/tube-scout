# Quickstart: Runtime Integration & Multi-Channel Auth Fix (spec 009)

**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md)

This is a 3-minute end-to-end run validating that spec 009's behavior
matches its acceptance criteria. Use this after implementation to
demonstrate the feature.

---

## Prerequisites

- `nix develop` shell active (or equivalent: `uv` env with all deps).
- `TUBE_SCOUT_CLIENT_SECRET_B64` (or path variant) set via agenix.
- One YouTube channel that you own (you'll register it as an alias).

## 0. Reset to a clean state (optional)

If you want to reproduce the legacy-token migration path:

```bash
# Backup any existing tokens (optional)
cp -r ~/.config/tube-scout ~/.config/tube-scout.bak
# Clean state
rm -rf ~/.config/tube-scout/tokens/
# Place a synthetic legacy token (or use a real prior one)
# (Skip this if no prior token.json exists — migration will be a no-op)
```

## 1. Register a channel (device flow)

```bash
tube-scout auth --channel nursing
```

Expected output:

```text
Visit: https://www.google.com/device
Code:  ABCD-EFGH
Expires in 15:00. Polling every 5s.
```

Open the URL in **any** browser (multi-account is fine). Enter the code.
Approve the consent screen. Within seconds:

```text
✓ Channel 'nursing' registered (UCnh...).
```

**Validation**: `tube-scout auth --list` shows `nursing` with both required
scopes. **No port 8080 listener was opened** during the flow (`ss -ltn` confirms).

If a legacy `token.json` was present, the first auth call also emits:

```text
[dim]Migrated legacy token.json → tokens/nursing.json (matched channel_id UCnh...).[/dim]
```

## 2. Collect videos (producer)

```bash
tube-scout collect videos --channel nursing
```

Expected:

```text
Using multi-channel auth for 'nursing'
Collecting videos for channel UCnh...
  Found 216 videos matching '홍길동'
Collected 216 videos successfully.
```

**Validation**:

```bash
readlink projects/latest
# → 20260507-001907 (or similar — points at the project just created)
ls projects/latest/01_collect/channels/UCnh.../videos_meta.json
# → exists, 216 videos
```

`projects/latest` was atomically advanced to the new project by the
producer's `commit_latest()` call.

## 3. Collect transcripts (consumer, no `--project` flag)

```bash
tube-scout collect transcripts --channel nursing
```

Expected (one line per video, dim for fallback-succeeded path):

```text
Captions API fallback enabled for private videos
  public_vid_002: 784 segments (manual)
  private_vid_001: 898 segments (captions_api, primary skipped: VideoUnavailable)
  ...
```

**Validation**:

```bash
ls projects/latest/01_collect/transcripts/ | wc -l
# → ≥1 (52 in the operator's first run)
python3 -c "import json; d=json.load(open('projects/latest/01_collect/transcripts/public_vid_002.json')); print(d.get('source'))"
# → manual
ls projects/latest/01_collect/transcripts_audit.csv
# → exists; one row per missed video
```

**No empty sibling project was created** in `projects/`:

```bash
ls -td projects/2026* | head -3
# → first entry matches projects/latest's target; no empty siblings
```

## 4. Collect retention (consumer, --channel now accepted)

```bash
tube-scout collect retention --channel nursing
```

Expected: succeeds **without** `invalid_scope: Bad Request`. Auth routes
through `tokens/nursing.json` (NOT legacy `token.json`).

**Validation**:

```bash
ls projects/latest/01_collect/retention/ | wc -l
# → number of videos with retention data
```

If the registry has only the `nursing` alias, you can also omit `--channel`:

```bash
tube-scout collect retention
# Output: "Using channel: nursing (only registered alias)"
```

If you have **two or more** aliases registered, omitting `--channel` prints
guidance instead:

```text
Multiple channels registered. Specify --channel <alias>.
Available aliases:
  - nursing  (UCnh...)  Last used 2026-05-07
  - dental   (UCab...)  Last used 2026-05-01
Run again with: tube-scout collect retention --channel nursing
```

## 5. Collect analytics + bulk (newly --channel-aware)

```bash
tube-scout collect analytics --channel nursing
tube-scout collect bulk --channel nursing
```

Both succeed and route through `tokens/nursing.json`.

## 6. Content scan + report bundle (consumers, no flag changes)

```bash
tube-scout content scan --channel nursing --year-from 2024 --year-to 2025
tube-scout report bundle --keyword "감염미생물학" --format pdf --dry-run
tube-scout report bundle --keyword "감염미생물학" --format pdf --output /tmp/test.pdf
```

Both auto-resolve `--project=latest` (today's behavior, preserved).

---

## What you just verified

| Acceptance | Verified by |
|---|---|
| SC-001 (full chain, alias only) | Steps 1–6 |
| SC-002 (OAuth ≤2 min, no hang) | Step 1 |
| SC-003 (no empty sibling) | Step 3 validation |
| SC-004 (legacy migration) | Step 1 dim line |
| SC-005 (multi-alias refusal) | Step 4 alternate flow |
| SC-006 (clean transcript output) | Step 3 single-line dim |
| SC-007 (audit CSV) | Step 3 validation |
| SC-008 (`source` field) | Step 3 python3 check |
| SC-009 (clean state on timeout) | (manual: walk away from device-code prompt) |

---

## Cleanup (if desired)

```bash
# Remove the test project (keeps OAuth registration)
rm -rf projects/<the-just-created-timestamp>

# Or revoke the channel registration entirely
tube-scout auth --revoke nursing
```
