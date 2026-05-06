# Contract: OAuth Flow (Device Code default + Browser Redirect opt-in)

**Spec**: [../spec.md](../spec.md) · **Plan**: [../plan.md](../plan.md)
**Source**: [research.md R1](../research.md) · spec FR-011 / FR-012 / FR-013

This contract defines the OAuth flow shape for `tube-scout auth --channel
<alias>` and any implicit re-auth triggered by `authenticate_channel(alias)`
when refresh fails.

---

## Default flow: Device Authorization Grant (RFC 8628)

### CLI surface

```text
tube-scout auth --channel <alias>
```

No additional flag required for device flow — it is the default.

### Sequence

```text
1. Operator runs:    tube-scout auth --channel nursing
2. CLI POSTs:        https://oauth2.googleapis.com/device/code
                     body: client_id, scope=force-ssl yt-analytics.readonly
3. Server responds:  device_code, user_code, verification_url,
                     expires_in (≈15min), interval (≈5s)
4. CLI prints:       
                     ┌─────────────────────────────────────────┐
                     │ Visit: https://www.google.com/device    │
                     │ Code:  ABCD-EFGH                        │
                     │ Expires in 15:00. Polling every 5s.     │
                     └─────────────────────────────────────────┘
5. Operator opens any browser (already logged in as channel owner),
   visits the URL, enters the code, approves the consent screen.
6. CLI polls:        POST https://oauth2.googleapis.com/token
                     grant_type=urn:ietf:params:oauth:grant-type:device_code
                     device_code, client_id, client_secret
   - authorization_pending → continue polling at `interval`
   - slow_down            → increase interval by 5s
   - expired_token        → DeviceCodeTimeout error, fail
   - access_denied        → DeviceCodeAccessDenied error, fail
   - 200 OK + token       → proceed to step 7
7. CLI persists:     ~/.config/tube-scout/tokens/<alias>.json (0600 atomic)
                     ~/.config/tube-scout/tokens/channels.json (registry update)
8. CLI prints:       ✓ Channel 'nursing' registered (UC...).
```

### Error states

| State | Cause | CLI behavior |
|---|---|---|
| `authorization_pending` | Operator hasn't approved yet | Continue polling at advertised interval |
| `slow_down` | Polling too fast | Increase interval; continue |
| `expired_token` | Operator took too long | Raise `DeviceCodeTimeout`; remove no partial token |
| `access_denied` | Operator pressed deny | Raise `DeviceCodeAccessDenied` |
| Network error during POST | DNS/connectivity | Raise `UserFacingError` with retry suggestion |
| Invalid client | Misconfigured agenix secret | Raise `UserFacingError` pointing at secret loader docs |

### Timeouts

- Device code expires per server's `expires_in` (Google: 15 minutes).
- CLI polling timeout = `expires_in`. CLI does NOT override.
- On expiry, CLI exits with non-zero code and a clear error.

### Filesystem invariants

- No partial `tokens/<alias>.json` is left on disk on any failure path.
- `tokens/channels.json` is updated only on successful token persist.
- Both files written 0600 atomically via `os.rename` from a sibling temp file.

---

## Opt-in flow: Browser Redirect (legacy)

### CLI surface

```text
tube-scout auth --channel <alias> --browser-redirect
```

### Sequence

Identical to today's `flow.run_local_server(port=8080)` flow.

### Headless guard (FR-012, idea6 NFR-IDEA6-003 / B7)

When `--browser-redirect` is requested but `_require_tty` detects no TTY,
the CLI **automatically falls back to the device-code flow** rather than
raising `InteractiveAuthRequired` directly. Rationale: the device flow does
not require a TTY for the redirect; only for printing the code. If even
stdout is not available (rare), `InteractiveAuthRequired` is raised.

### Error states

Same as today: invalid_scope, invalid_client, port already in use, callback
hang (D-17). The hang is no longer the default failure surface; operators
who explicitly opt into redirect accept the risk.

---

## Implicit re-auth (refresh failure)

When `authenticate_channel(alias)` is called and the stored token's refresh
also fails (e.g., revoked, scope-deficient), the CLI MUST surface an
actionable error rather than silently re-running OAuth. The error directs
the operator to run `tube-scout auth --channel <alias>` (which uses the
device flow by default).

```text
ERROR: Stored token for 'nursing' is no longer valid.
       Cause: refresh_token revoked or scopes insufficient.
Next:  tube-scout auth --channel nursing
```

---

## Test contract

| Scenario | Test type | Location |
|---|---|---|
| Device code → success | contract (httpx_mock) | `tests/contract/test_auth_device_flow.py` |
| Device code → authorization_pending → success | contract (httpx_mock) | same |
| Device code → slow_down → backoff → success | contract (httpx_mock) | same |
| Device code → expired_token → DeviceCodeTimeout | contract (httpx_mock) | same |
| Device code → access_denied → DeviceCodeAccessDenied | contract (httpx_mock) | same |
| Browser redirect, headless → falls back to device flow | unit | `tests/unit/test_auth_flow_selection.py` |
| Implicit re-auth on refresh failure → guidance error | integration | `tests/integration/test_implicit_reauth.py` |
| Real OAuth against Google (manual) | excluded from default suite | `tests/manual/test_real_oauth_device_flow.py` |

---

## Invariants

- Device-code flow is the default for `auth --channel <alias>`.
- `--browser-redirect` is the only path that uses local-server redirect.
- Headless contexts NEVER bind a TCP listener.
- No partial token file or registry row on any failure path.
- Both flows persist tokens 0600 atomic.
- Both flows verify scopes via existing `_verify_scopes` (idea6) before persisting.
