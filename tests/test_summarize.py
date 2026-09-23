"""Summaries fall back to recorded results when the model invents a measurement."""

from __future__ import annotations

import json

from api_watch.errors import LLMError
from api_watch.models import CheckResult
from api_watch.prompts import SYSTEM_PROMPT
from api_watch.summarize import parse_summary, summarize_failures


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


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.system = ""
        self.user = ""
        self.closed = False

    def complete(self, *, system: str, user: str) -> str:
        self.system = system
        self.user = user
        return self.content

    def close(self) -> None:
        self.closed = True


class BoomClient:
    def complete(self, *, system: str, user: str) -> str:
        raise LLMError("Could not reach Ollama at http://127.0.0.1:11434.")

    def close(self) -> None:
        return None


def test_grounded_model_text_is_kept() -> None:
    client = FakeClient(
        json.dumps(
            {
                "bullets": [
                    {
                        "name": "billing",
                        "sentence": "billing returned status 503 in 12.5 ms.",
                    }
                ]
            }
        )
    )
    outcome = summarize_failures([_failure()], client)
    assert outcome.source == "model"
    assert outcome.warnings == []
    assert "status 503 in 12.5 ms" in outcome.text
    assert "https://evil.test" not in outcome.text
    assert client.system == SYSTEM_PROMPT
    assert "https://example.test/health" in client.user
    assert "https://example.test/ok" not in client.user


def test_invented_facts_fall_back_to_the_recorded_line() -> None:
    client = FakeClient(
        json.dumps(
            {
                "bullets": [
                    {
                        "name": "billing",
                        "sentence": "billing at https://evil.test returned status 404 in 999 ms.",
                    }
                ]
            }
        )
    )
    outcome = summarize_failures([_failure()], client)
    assert outcome.source == "recorded"
    assert "https://example.test/health" in outcome.text
    assert "status 503" in outcome.text
    assert "12.5 ms" in outcome.text
    assert "https://evil.test" not in outcome.text
    assert "404" not in outcome.text
    assert "999" not in outcome.text
    assert outcome.warnings


def test_unusable_model_output_falls_back() -> None:
    for content in ("not-json", json.dumps({"bullets": []}), ""):
        outcome = summarize_failures([_failure()], FakeClient(content or "{"))
        assert outcome.source == "recorded"
        assert "https://example.test/health" in outcome.text
        assert "404" not in outcome.text


def test_model_transport_errors_fall_back_without_raising() -> None:
    outcome = summarize_failures([_failure()], BoomClient())
    assert outcome.source == "recorded"
    assert "Could not reach Ollama" in outcome.warnings[0]
    assert "https://example.test/health" in outcome.text


def test_parse_summary_accepts_a_bare_array() -> None:
    parsed = parse_summary(
        json.dumps([{"name": "billing", "sentence": "billing failed.", "extra": True}])
    )
    assert parsed.bullets[0].name == "billing"
    assert parsed.bullets[0].sentence == "billing failed."
