"""HTTP checks use a mock transport. Nothing here dials a real host."""

from __future__ import annotations

import httpx
import pytest

from api_watch import __version__
from api_watch.checker import run_checks
from api_watch.models import Target


def _target(**overrides: object) -> Target:
    data: dict[str, object] = {
        "name": "billing",
        "url": "https://example.test/health",
        "method": "GET",
        "expect_status": 200,
        "timeout_seconds": 5,
        "headers": {},
    }
    data.update(overrides)
    return Target.model_validate(data)


def _client(handler: httpx.MockTransport | object) -> httpx.Client:
    transport = handler if isinstance(handler, httpx.MockTransport) else httpx.MockTransport(handler)  # type: ignore[arg-type]
    return httpx.Client(transport=transport)


def test_pass_fail_and_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/down"):
            return httpx.Response(503)
        if request.method == "POST":
            return httpx.Response(204)
        return httpx.Response(200)

    targets = [
        _target(name="ok"),
        _target(name="down", url="https://example.test/down"),
        _target(name="create", url="https://example.test/items", method="POST", expect_status=204),
    ]
    results = run_checks(targets, client=_client(handler))
    assert [item.ok for item in results] == [True, False, True]
    assert results[0].status_code == 200
    assert results[0].error is None
    assert results[0].latency_ms is not None and results[0].latency_ms >= 0
    assert results[1].status_code == 503
    assert results[1].error == "expected status 200, got 503"
    assert results[2].status_code == 204


def test_timeout_and_connection_errors_are_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/slow"):
            raise httpx.ReadTimeout("timed out")
        raise httpx.ConnectError("connection refused")

    results = run_checks(
        [
            _target(name="slow", url="https://example.test/slow", timeout_seconds=5),
            _target(name="down", url="https://example.test/down"),
        ],
        client=_client(handler),
    )
    assert results[0].ok is False
    assert results[0].status_code is None
    assert results[0].error == "timeout after 5s"
    assert results[0].latency_ms is not None
    assert results[1].ok is False
    assert results[1].status_code is None
    assert results[1].error is not None
    assert "connection failed" in results[1].error


def test_unexpected_error_does_not_abort_the_batch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/boom"):
            raise RuntimeError("boom")
        return httpx.Response(200)

    results = run_checks(
        [_target(name="boom", url="https://example.test/boom"), _target(name="ok")],
        client=_client(handler),
    )
    assert results[0].ok is False
    assert results[0].error == "unexpected error: boom"
    assert results[1].ok is True


def test_sends_user_agent_and_resolved_headers() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["user-agent"] = request.headers["user-agent"]
        seen["authorization"] = request.headers["authorization"]
        seen["x-source"] = request.headers["x-source"]
        return httpx.Response(200)

    run_checks(
        [
            _target(
                headers={
                    "Authorization": "secret-token",
                    "X-Source": "east",
                    "User-Agent": "custom-probe",
                }
            )
        ],
        client=_client(handler),
    )
    assert seen["authorization"] == "secret-token"
    assert seen["x-source"] == "east"
    assert seen["user-agent"] == "custom-probe"

    def default_agent(request: httpx.Request) -> httpx.Response:
        seen["default-agent"] = request.headers["user-agent"]
        return httpx.Response(200)

    run_checks([_target()], client=_client(default_agent))
    assert seen["default-agent"] == f"api-watch/{__version__}"


def test_default_client_follows_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    import api_watch.checker as checker

    seen: dict[str, object] = {}
    real = httpx.Client

    def factory(*args: object, **kwargs: object) -> httpx.Client:
        seen.update(kwargs)
        kwargs["transport"] = httpx.MockTransport(lambda request: httpx.Response(200))
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(checker.httpx, "Client", factory)
    results = run_checks([_target()])
    assert results[0].ok is True
    assert seen["follow_redirects"] is True
