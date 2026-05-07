"""Manual E2E test: real Google OAuth device-code flow (Spec 009 / SC-002).

This test is **NOT** part of the default pytest suite (idea6 D-9:
``norecursedirs = ["tests/manual"]`` in ``pyproject.toml``). It hits real
Google endpoints and requires a live operator to complete consent.

Run explicitly:

    uv run pytest tests/manual/test_real_oauth_device_flow.py -v -s \\
        --override-ini="norecursedirs="

Preconditions:

1. ``TUBE_SCOUT_CLIENT_SECRET`` env var (or ``TUBE_SCOUT_CLIENT_SECRET_B64``)
   resolves to a valid OAuth ``client_secret.json`` for a Google Cloud
   project of type **TVs and Limited Input devices**. (A web client type
   produces ``invalid_client`` against the device endpoint and the test
   will fail fast with ``ClientTypeNotSupportedForDeviceFlow``.)
2. ``TUBE_SCOUT_TEST_ALIAS`` env var names the alias to register
   (default: ``test_device_flow``). Any pre-existing alias by this name
   will be overwritten.
3. Operator must be ready to open the verification URL in a browser
   and approve the device code within 120 seconds.

Acceptance:

- Test artifact ``device_flow_duration.json`` records wall-clock seconds
  from device-code request to token receipt (SC-002 budget = 120s).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest


@pytest.mark.skipif(
    "CI" in os.environ,
    reason="Manual OAuth E2E — operator interaction required (SC-002).",
)
def test_real_oauth_device_flow_under_120_seconds(tmp_path: Path) -> None:
    """Walk an operator through device-code consent against real Google.

    Asserts wall-clock duration ≤ 120 seconds (Spec 009 SC-002).
    """
    from tube_scout.services.auth import SCOPES
    from tube_scout.services.auth_device_flow import DeviceFlow
    from tube_scout.services.secret_loader import resolve_client_secret_path

    alias = os.environ.get("TUBE_SCOUT_TEST_ALIAS", "test_device_flow")

    secret_path = resolve_client_secret_path()
    secret_data = json.loads(Path(secret_path).read_text(encoding="utf-8"))
    client = secret_data.get("installed") or secret_data.get("web") or {}
    client_id = client["client_id"]
    client_secret = client["client_secret"]

    flow = DeviceFlow(
        client_id=client_id,
        client_secret=client_secret,
        alias=alias,
    )

    started = time.monotonic()
    device_resp = flow.fetch_device_code(scopes=list(SCOPES))

    print()
    print("=" * 60)
    print(f"Open: {device_resp['verification_url']}")
    print(f"Code: {device_resp['user_code']}")
    print(f"Approve as the channel owner of alias '{alias}'.")
    print("=" * 60)
    print()

    token = flow.poll_token(
        device_code=device_resp["device_code"],
        interval=device_resp.get("interval", 5),
        expires_in=device_resp.get("expires_in", 1800),
    )
    elapsed = time.monotonic() - started

    artifact_path = tmp_path / "device_flow_duration.json"
    artifact_path.write_text(
        json.dumps(
            {
                "alias": alias,
                "elapsed_seconds": round(elapsed, 2),
                "sc_002_budget_seconds": 120,
                "passed": elapsed <= 120,
                "received_refresh_token": "refresh_token" in token,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"Device flow completed in {elapsed:.1f}s "
        f"(budget 120s). Artifact: {artifact_path}"
    )

    assert "access_token" in token, "Device flow returned no access_token"
    assert "refresh_token" in token, "Device flow returned no refresh_token"
    assert elapsed <= 120, (
        f"SC-002 violation: device flow took {elapsed:.1f}s (>120s budget)"
    )
