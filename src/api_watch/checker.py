"""Run HTTP checks. Pass or fail comes from the response, never from a model."""

from __future__ import annotations

import time

import httpx

from api_watch import __version__
from api_watch.models import CheckResult, Target


def run_checks(targets: list[Target], *, client: httpx.Client | None = None) -> list[CheckResult]:
    """Check each target once, in order. One failure does not stop the rest."""
    owns_client = client is None
    http = client or httpx.Client(follow_redirects=True)
    try:
        return [check_target(http, target) for target in targets]
    finally:
        if owns_client:
            http.close()


def check_target(client: httpx.Client, target: Target) -> CheckResult:
    """Probe one URL. Timeouts and connection errors are failures with a reason."""
    headers = {"User-Agent": f"api-watch/{__version__}"}
    headers.update(target.headers)
    started = time.perf_counter()
    try:
        response = client.request(
            target.method,
            target.url,
            headers=headers,
            timeout=target.timeout_seconds,
        )
    except httpx.TimeoutException:
        return _result(
            target,
            ok=False,
            status_code=None,
            latency_ms=_elapsed_ms(started),
            error=f"timeout after {_format_seconds(target.timeout_seconds)}s",
        )
    except httpx.RequestError as exc:
        return _result(
            target,
            ok=False,
            status_code=None,
            latency_ms=_elapsed_ms(started),
            error=f"connection failed: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 - one bad target must not abort the batch
        return _result(
            target,
            ok=False,
            status_code=None,
            latency_ms=_elapsed_ms(started),
            error=f"unexpected error: {exc}",
        )

    latency_ms = _elapsed_ms(started)
    if response.status_code != target.expect_status:
        return _result(
            target,
            ok=False,
            status_code=response.status_code,
            latency_ms=latency_ms,
            error=f"expected status {target.expect_status}, got {response.status_code}",
        )
    return _result(
        target,
        ok=True,
        status_code=response.status_code,
        latency_ms=latency_ms,
        error=None,
    )


def _result(
    target: Target,
    *,
    ok: bool,
    status_code: int | None,
    latency_ms: float,
    error: str | None,
) -> CheckResult:
    return CheckResult(
        name=target.name,
        url=target.url,
        method=target.method,
        ok=ok,
        expected_status=target.expect_status,
        status_code=status_code,
        latency_ms=latency_ms,
        error=error,
    )


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _format_seconds(value: float) -> str:
    return f"{value:g}"
