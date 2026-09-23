"""A summary line is kept only when it cites this run's recorded facts."""

from __future__ import annotations

from api_watch.guard import guard_summary
from api_watch.models import CheckResult, LLMSummary


def _failure(**overrides: object) -> CheckResult:
    data: dict[str, object] = {
        "name": "billing",
        "url": "https://example.test/health",
        "method": "GET",
        "ok": False,
        "expected_status": 200,
        "status_code": 503,
        "latency_ms": 12.5,
        "error": "expected status 200, got 503",
    }
    data.update(overrides)
    return CheckResult.model_validate(data)


def _summary(name: str, sentence: str) -> LLMSummary:
    return LLMSummary.model_validate({"bullets": [{"name": name, "sentence": sentence}]})


def test_keeps_a_sentence_that_copies_recorded_facts() -> None:
    kept, dropped = guard_summary(
        [_failure()],
        _summary(
            "billing",
            "billing GET https://example.test/health returned status 503 in 12.5 ms.",
        ),
    )
    assert dropped == []
    assert kept[0].sentence.startswith("billing GET")


def test_keeps_a_sentence_with_no_numbers() -> None:
    kept, dropped = guard_summary([_failure()], _summary("billing", "billing failed."))
    assert dropped == []
    assert len(kept) == 1


def test_drops_unknown_invented_and_repeated_lines() -> None:
    failures = [_failure()]
    summary = LLMSummary.model_validate(
        {
            "bullets": [
                {"name": "payments", "sentence": "payments returned status 404."},
                {"name": "billing", "sentence": "billing at https://evil.test failed."},
                {"name": "billing", "sentence": "billing returned status 404."},
                {"name": "billing", "sentence": "billing took 999 ms."},
                {"name": "billing", "sentence": "billing returned status 503."},
                {"name": "billing", "sentence": "billing returned status 503 again."},
                {"name": "", "sentence": "something failed."},
            ]
        }
    )
    kept, dropped = guard_summary(failures, summary)
    assert [item.sentence for item in kept] == ["billing returned status 503."]
    joined = "\n".join(dropped)
    assert "payments: not a failed check" in joined
    assert "endpoint https://evil.test is not in the check result" in joined
    assert "status code 404 is not in the check result" in joined
    assert "latency 999 ms is not in the check result" in joined
    assert "billing: repeated target" in joined
    assert "(blank): not a failed check" in joined


def test_expected_status_is_allowed_and_latency_is_not_a_status_code() -> None:
    failure = _failure(expected_status=201, status_code=500, latency_ms=200.0)
    kept, dropped = guard_summary(
        [failure],
        _summary("billing", "expected status 201, got status 500 in 200.0 ms."),
    )
    assert dropped == []
    assert kept

    kept_bad, dropped_bad = guard_summary(
        [failure],
        _summary("billing", "billing returned status 404 in 200.0 ms."),
    )
    assert kept_bad == []
    assert "404" in dropped_bad[0]


def test_null_latency_rejects_a_made_up_duration() -> None:
    failure = _failure(status_code=None, latency_ms=None, error="timeout after 5s")
    kept, dropped = guard_summary(
        [failure],
        _summary("billing", "billing timed out after 5s and took 40 ms."),
    )
    assert kept == []
    assert "latency was not recorded" in dropped[0]

    kept_ok, dropped_ok = guard_summary(
        [failure],
        _summary("billing", "billing timed out. expected status 200."),
    )
    assert dropped_ok == []
    assert kept_ok
