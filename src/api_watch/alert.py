"""Failure alerts: stderr lines, and an optional JSON webhook."""

from __future__ import annotations

import httpx

from api_watch.errors import AlertError
from api_watch.models import CheckResult


def format_alerts(failures: list[CheckResult]) -> str:
    """One stderr line per failed check. The reason is the recorded error."""
    return "\n".join(f"ALERT {item.name}: {item.error or 'failed'}" for item in failures)


def post_webhook(
    url: str,
    payload: dict[str, object],
    *,
    client: httpx.Client | None = None,
) -> None:
    """POST the run JSON. Raises AlertError and does not change the check exit code."""
    owns_client = client is None
    http = client or httpx.Client(timeout=10.0)
    try:
        try:
            response = http.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise AlertError(f"Webhook request failed: {exc}") from exc
        if response.status_code >= 400:
            detail = response.text.strip().replace("\n", " ")[:300]
            raise AlertError(f"Webhook returned HTTP {response.status_code}: {detail}")
    finally:
        if owns_client:
            http.close()
