"""OAuth 2.0 Device Authorization Grant (RFC 8628) for headless auth.

Spec 009 FR-011 / FR-013. The device flow is the default for
``tube-scout auth --channel <alias>``: it does not require a TCP
listener and works in multi-account browser environments.

Endpoints (Google):
    https://oauth2.googleapis.com/device/code
    https://oauth2.googleapis.com/token

Polling states (RFC 8628 §3.5):
    authorization_pending → continue at advertised interval
    slow_down            → increase interval by 5 seconds
    expired_token        → DeviceCodeTimeout
    access_denied        → DeviceCodeAccessDenied
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

DEVICE_AUTH_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GRANT_TYPE_DEVICE_CODE = "urn:ietf:params:oauth:grant-type:device_code"


class DeviceFlow:
    """Synchronous client for RFC 8628 device authorization grant.

    Args:
        client_id: OAuth client identifier (from agenix-resolved client secret).
        client_secret: OAuth client secret (from agenix-resolved client secret).
        alias: Channel alias surfaced in error messages. Defaults to ``"default"``.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        alias: str = "default",
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.alias = alias

    def fetch_device_code(self, *, scopes: list[str]) -> dict[str, Any]:
        """POST /device/code and return the server payload.

        Args:
            scopes: List of OAuth scope URIs.

        Returns:
            Mapping with ``device_code``, ``user_code``, ``verification_url``,
            ``expires_in`` (seconds), ``interval`` (seconds).

        Raises:
            UserFacingError: Network or HTTP error reaching the endpoint.
        """
        from tube_scout.cli.errors import UserFacingError  # noqa: PLC0415

        body = {"client_id": self.client_id, "scope": " ".join(scopes)}
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(DEVICE_AUTH_URL, data=body)
        except httpx.HTTPError as exc:
            raise UserFacingError(
                message=(
                    f"Could not reach Google device-code endpoint ({exc.__class__.__name__})."
                ),
                next_command=f"tube-scout auth --channel {self.alias}",
            ) from exc

        if resp.status_code == 401:
            from tube_scout.cli.errors import ClientTypeNotSupportedForDeviceFlow  # noqa: PLC0415

            raise ClientTypeNotSupportedForDeviceFlow(alias=self.alias)

        if resp.status_code != 200:
            raise UserFacingError(
                message=(
                    f"Google device-code endpoint returned HTTP {resp.status_code}: "
                    f"{resp.text[:200]}"
                ),
                next_command=f"tube-scout auth --channel {self.alias}",
            )
        return resp.json()

    def poll_token(
        self,
        *,
        device_code: str,
        interval: int,
        expires_in: int,
        _capture_intervals: list[float] | None = None,
    ) -> dict[str, Any]:
        """Poll /token until the operator approves or the device code expires.

        Args:
            device_code: The device_code from :meth:`fetch_device_code`.
            interval: Server-advertised polling interval (seconds).
            expires_in: Server-advertised lifetime of the device code (seconds).
            _capture_intervals: Test hook — appended each iteration.

        Returns:
            Token mapping with ``access_token``, ``refresh_token``, etc.

        Raises:
            DeviceCodeTimeout: Server returned ``expired_token`` (RFC 8628 §3.5).
            DeviceCodeAccessDenied: Operator declined the consent screen.
            UserFacingError: Network error during polling.
        """
        from tube_scout.cli.errors import (  # noqa: PLC0415
            DeviceCodeAccessDenied,
            DeviceCodeTimeout,
            UserFacingError,
        )

        body = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "device_code": device_code,
            "grant_type": GRANT_TYPE_DEVICE_CODE,
        }
        deadline = time.monotonic() + expires_in
        current_interval = interval
        while True:
            if _capture_intervals is not None:
                _capture_intervals.append(current_interval)
            if current_interval > 0:
                time.sleep(current_interval)
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.post(TOKEN_URL, data=body)
            except httpx.HTTPError as exc:
                raise UserFacingError(
                    message=(
                        f"Network error while polling Google token endpoint "
                        f"({exc.__class__.__name__})."
                    ),
                    next_command=f"tube-scout auth --channel {self.alias}",
                ) from exc

            if resp.status_code == 200:
                return resp.json()

            try:
                payload = resp.json() if resp.content else {}
            except ValueError as exc:
                raise UserFacingError(
                    message=(
                        f"Google token endpoint returned non-JSON content "
                        f"(HTTP {resp.status_code}): {resp.text[:200]!r}."
                    ),
                    next_command=f"tube-scout auth --channel {self.alias}",
                ) from exc
            error = payload.get("error", "")
            if error == "authorization_pending":
                pass
            elif error == "slow_down":
                current_interval = current_interval + 5
            elif error == "expired_token":
                raise DeviceCodeTimeout(alias=self.alias)
            elif error == "access_denied":
                raise DeviceCodeAccessDenied(alias=self.alias)
            else:
                raise UserFacingError(
                    message=(
                        f"Unexpected response from Google token endpoint: "
                        f"HTTP {resp.status_code} {payload}"
                    ),
                    next_command=f"tube-scout auth --channel {self.alias}",
                )

            if time.monotonic() >= deadline:
                raise DeviceCodeTimeout(alias=self.alias)

    def run(
        self,
        *,
        scopes: list[str],
        on_code: Callable[[str, str, int], None],
        token_path: Path | None = None,
        _capture_intervals: list[float] | None = None,
    ) -> dict[str, Any]:
        """Execute the full device flow end-to-end.

        Args:
            scopes: List of OAuth scope URIs.
            on_code: Callback invoked once with ``(user_code, verification_url,
                expires_in)`` so the CLI can render the consent prompt.
            token_path: Optional path that MUST NOT contain a partial token on
                any failure path (verification hook).
            _capture_intervals: Test hook for asserting backoff behavior.

        Returns:
            Token mapping on operator approval.

        Raises:
            DeviceCodeTimeout: Operator did not approve before expiry.
            DeviceCodeAccessDenied: Operator declined consent.
            UserFacingError: Network or protocol error.
        """
        from tube_scout.cli.errors import UserFacingError  # noqa: PLC0415

        try:
            device_resp = self.fetch_device_code(scopes=scopes)
            for required in ("device_code", "user_code", "verification_url"):
                if required not in device_resp:
                    raise UserFacingError(
                        message=(
                            f"Google device-code response missing required field "
                            f"'{required}': {device_resp}."
                        ),
                        next_command=f"tube-scout auth --channel {self.alias}",
                    )
            on_code(
                device_resp["user_code"],
                device_resp["verification_url"],
                device_resp.get("expires_in", 1800),
            )
            return self.poll_token(
                device_code=device_resp["device_code"],
                interval=device_resp.get("interval", 5),
                expires_in=device_resp.get("expires_in", 1800),
                _capture_intervals=_capture_intervals,
            )
        except BaseException:
            if token_path is not None and token_path.exists():
                token_path.unlink()
            raise
