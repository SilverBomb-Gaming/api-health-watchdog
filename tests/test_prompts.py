"""The model is told, in the prompt, not to invent endpoints, status codes, or latencies."""

from __future__ import annotations

import re

from api_watch.models import CheckResult
from api_watch.prompts import SYSTEM_PROMPT, build_user_prompt

_FORBIDDEN = (
    "Do not invent endpoints, status codes, or latencies that are not present in the check results."
)


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


def test_system_prompt_forbids_fabrication() -> None:
    assert _FORBIDDEN in SYSTEM_PROMPT
    assert "Do not add a target that is not in the JSON." in SYSTEM_PROMPT
    assert "If status_code is null, do not invent a status code." in SYSTEM_PROMPT
    assert "If latency_ms is null, do not invent a latency." in SYSTEM_PROMPT
    assert "copy latency_ms" in SYSTEM_PROMPT
    assert "Copy name" in SYSTEM_PROMPT or "copied from a name" in SYSTEM_PROMPT


def test_system_prompt_contains_no_sample_measurements() -> None:
    assert "http://" not in SYSTEM_PROMPT
    assert "https://" not in SYSTEM_PROMPT
    assert re.search(r"\b[1-5]\d{2}\b", SYSTEM_PROMPT) is None
    assert re.search(r"\b\d+(?:\.\d+)?\s*ms\b", SYSTEM_PROMPT) is None


def test_user_prompt_repeats_the_rule_and_embeds_only_the_supplied_failures() -> None:
    prompt = build_user_prompt([_failure()])
    assert _FORBIDDEN in prompt
    assert "https://example.test/health" in prompt
    assert "503" in prompt
    assert "12.5" in prompt
    assert "billing" in prompt
    assert "https://other.test" not in prompt
    assert "404" not in prompt
    assert "999" not in prompt


def test_user_prompt_omits_a_check_it_was_not_given() -> None:
    prompt = build_user_prompt([_failure(name="billing")])
    assert "payments" not in prompt
