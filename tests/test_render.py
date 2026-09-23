"""Tables and recorded summaries print only measured fields."""

from __future__ import annotations

import json

from api_watch.models import CheckResult, Target
from api_watch.render import dump_json, render_plan, render_recorded_summary, render_table


def test_table_marks_pass_and_fail() -> None:
    text = render_table(
        [
            CheckResult(
                name="ok",
                url="https://example.test/ok",
                method="GET",
                ok=True,
                expected_status=200,
                status_code=200,
                latency_ms=8,
                error=None,
            ),
            CheckResult(
                name="down",
                url="https://example.test/down",
                method="GET",
                ok=False,
                expected_status=200,
                status_code=None,
                latency_ms=5,
                error="timeout after 5s",
            ),
        ],
        checked_at="2026-09-23T20:46:00Z",
        config_path="samples/local.yaml",
    )
    assert text.startswith("2026-09-23T20:46:00Z  samples/local.yaml\n")
    assert "PASS" in text
    assert "FAIL" in text
    assert "timeout after 5s" in text
    assert "8.0 ms" in text
    assert "-" in text


def test_plan_lists_header_names_only() -> None:
    text = render_plan(
        [
            Target(
                name="billing",
                url="https://example.test/health",
                headers={"Authorization": "secret-token"},
            )
        ],
        config_path="targets.yaml",
    )
    assert "Planned checks (1) from targets.yaml" in text
    assert "headers: Authorization" in text
    assert "secret-token" not in text
    assert "No requests sent." in text


def test_recorded_summary_copies_the_result() -> None:
    text = render_recorded_summary(
        [
            CheckResult(
                name="billing",
                url="https://example.test/health",
                method="GET",
                ok=False,
                expected_status=200,
                status_code=503,
                latency_ms=12.5,
                error="expected status 200, got 503",
            )
        ]
    )
    assert text == (
        "1 failed check.\n"
        "- billing GET https://example.test/health: expected status 200, got 503 "
        "(status 503, latency 12.5 ms)\n"
    )


def test_compact_json_is_one_line() -> None:
    text = dump_json({"ok": False, "failure_count": 1}, compact=True)
    assert "\n" not in text.strip()
    assert json.loads(text)["failure_count"] == 1
