"""Webhooks receive the run JSON. Delivery failures stay on the alert path."""

from __future__ import annotations

import json

import httpx
import pytest

from api_watch.alert import format_alerts, post_webhook
from api_watch.errors import AlertError
from api_watch.models import CheckResult


def _failure() -> CheckResult:
    return CheckResult(
        name="billing",
        url="https://example.test/health",
        method="GET",
        ok=False,
        expected_status=200,
        status_code=503,
        latency_ms=12.5,
        error="expected status 200, got 503",
    )


def test_alert_lines_use_the_recorded_reason() -> None:
    text = format_alerts([_failure()])
    assert text == "ALERT billing: expected status 200, got 503"


def test_webhook_posts_the_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        captured["content-type"] = request.headers["content-type"]
        return httpx.Response(204)

    payload = {"ok": False, "failure_count": 1, "results": [_failure().model_dump()]}
    post_webhook(
        "https://hooks.example.test/alerts",
        payload,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert captured["url"] == "https://hooks.example.test/alerts"
    assert captured["body"] == payload
    assert "application/json" in str(captured["content-type"])


def test_webhook_http_error_is_an_alert_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(AlertError, match="Webhook request failed"):
        post_webhook(
            "https://hooks.example.test/alerts",
            {"ok": False},
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )


def test_webhook_status_is_an_alert_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="nope")

    with pytest.raises(AlertError, match="HTTP 500"):
        post_webhook(
            "https://hooks.example.test/alerts",
            {"ok": False},
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
