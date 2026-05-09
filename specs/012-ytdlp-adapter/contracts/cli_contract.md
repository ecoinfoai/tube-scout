# Contract: `cli/collect.py` 확장

Typer CLI surface — Constitution IV CLI-First. 신규 subcommand 2개 + 기존 1개 확장 + flag 3개 + 환경변수 3개.

## Commands

### `tube-scout collect transcripts` (MODIFY)

```text
Usage: tube-scout collect transcripts [OPTIONS]

  Fetch transcripts (captions) for videos. Source api (Data API quota) or
  ytdlp (yt-dlp + cookies, no quota).

Options:
  --source [api|ytdlp]            Source. Priority: flag > env
                                  TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE > 'api'
                                  (spec 010 backward compat).
  --channel TEXT                  Channel alias (mutually exclusive with --all-channels).
  --all-channels                  Process all registered self-channels (FR-011a).
  --force                         Overwrite existing transcript JSON. Default: skip.
  --cookies-browser TEXT          Override cookies browser. Default: brave (or env
                                  TUBE_SCOUT_COOKIES_BROWSER).
  --cookies-file PATH             Override cookies.txt path. Default: env
                                  TUBE_SCOUT_COOKIES_FILE or
                                  ~/.config/tube-scout/cookies.txt (0600).
  --sleep-min FLOAT               Min sleep between calls. Default: 30.0.
  --sleep-max FLOAT               Max sleep between calls. Default: 60.0.
  --help                          Show this message and exit.
```

### `tube-scout collect audio` (NEW)

```text
Usage: tube-scout collect audio [OPTIONS]

  Extract audio + fingerprint + delete audio. Single command for the full
  P2 lifecycle (Constitution V — audio file 영속 0). For fingerprint-only
  re-run on existing audio_fingerprint table, use `collect fingerprint --force`.

Options:
  --channel TEXT                  Channel alias.
  --all-channels                  All registered self-channels.
  --force                         Re-extract even if fingerprint exists.
  --cookies-browser TEXT          (same as transcripts)
  --cookies-file PATH             (same as transcripts)
  --sleep-min FLOAT               (same)
  --sleep-max FLOAT               (same)
  --help                          Show this message and exit.
```

### `tube-scout collect fingerprint` (NEW)

```text
Usage: tube-scout collect fingerprint [OPTIONS]

  Alias for `collect audio` — extract audio, compute fingerprint, delete audio.
  Provided for operator semantic clarity (audio is intermediate, fingerprint
  is the persistent product).

Options:
  (same as `collect audio`)
```

## Environment variables

| Variable | Effect | Override priority |
|---|---|---|
| `TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE` | `api` or `ytdlp` — default for `collect transcripts --source` | flag > env > `api` |
| `TUBE_SCOUT_COOKIES_BROWSER` | Default browser for `--cookies-from-browser` | flag > env > `brave` |
| `TUBE_SCOUT_COOKIES_FILE` | Default cookies.txt path | flag > env > `~/.config/tube-scout/cookies.txt` (if exists) |

agenix 호환: `.envrc` 또는 cron 환경에서 1줄 설정. Constitution VI 준수.

## Exit code patterns

| Exit code | Trigger | Audit behavior |
|---|---|---|
| 0 | All channels processed (some videos may have failed individually) | per-video audit-log; channel summary stdout |
| 1 | Generic error / argument parse fail | stderr actionable + no audit row |
| 2 | `--channel` and `--all-channels` mutually exclusive (or both missing) | stderr actionable |
| 3 | Cookies source unresolvable (none of browser / file / default works) | stderr actionable + no API call made |
| 4 | All channels failed cookies (rate limit / auth) | per-channel audit "cookies_expired" or "rate_limit" |
| 5 | Channel alias not registered (FR-019 — external channel reject) | stderr actionable |
| 130 | SIGINT (Ctrl+C) | per-video audit "interrupted" + audio_temp cleanup attempt |
| 143 | SIGTERM | (same as SIGINT) |

## CLI scenarios (RED-first)

`tests/unit/test_collect_cli.py` — 12 시나리오:

1. **`collect transcripts` 디폴트 = api** (env 미설정): Typer args에 `source="api"` 전달.
2. **env `TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE=ytdlp` + 플래그 무**: source="ytdlp".
3. **flag `--source api` + env `=ytdlp`**: flag 우선 → source="api".
4. **`--channel nursing` + `--all-channels`** 동시 → exit code 2 + stderr actionable.
5. **`--channel <unknown>` (미등록)**: exit code 5 + actionable + yt-dlp 호출 0건.
6. **`--all-channels` + 22채널 등록**: alias 22개 순차 처리, 1개 채널 fail 시 exit code 0 + 21채널 정상 처리 (FR-016 isolation).
7. **`collect audio` + `--force`**: 기존 fingerprint row → INSERT OR REPLACE, audit "captured".
8. **`collect audio` 미명시 (idempotent)**: 기존 row → audit "skip_existing".
9. **SIGINT mid-channel**: signal handler가 audio_temp 정리 + audit "interrupted" + exit 130.
10. **Cookies file perms != 0600**: env path 의 권한이 0644 → exit code 3 + actionable "Run `chmod 600 <path>`".
11. **Cookies 모두 부재**: 환경변수 미설정 + 디폴트 path 미존재 + Brave keyring locked → exit 3 + actionable.
12. **`collect fingerprint` 별칭 작동**: `collect fingerprint --channel x` 와 `collect audio --channel x` 의 효과 동등 (subprocess 동일 args).

## Boundary references

- B-X1-4: `--channel <alias>` 과 `--all-channels` 모두 spec 003 alias resolver 사용
- B-X1-5: `--source api` flow는 spec 009 OAuth token 재사용 (변경 0)
- B-X1-6: Cookies env vars 3개 모두 agenix 적용 가능
- B-X1-7: `--all-channels` 시 채널 isolation (한 채널 fail 다른 채널 진행)
- Constitution IV: CLI 가 service-layer 의 thin wrapper, 비즈니스 로직 0
- Constitution II: 모든 exit non-0 사이트가 actionable + stderr
