"""Turn a failure batch into a short summary, then drop anything the checks do not support."""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError

from api_watch.errors import LLMError, UsageError
from api_watch.guard import guard_summary
from api_watch.llm import LLMClient
from api_watch.models import CheckResult, LLMSummary
from api_watch.prompts import SYSTEM_PROMPT, build_user_prompt
from api_watch.render import render_model_summary, render_recorded_summary


class SummaryParseError(UsageError):
    """The model replied, but the body was not the summary object we asked for."""


@dataclass(frozen=True)
class SummaryOutcome:
    """text is safe to print. source is 'model' or 'recorded'."""

    text: str
    source: str
    warnings: list[str]


def summarize_failures(failures: list[CheckResult], client: LLMClient) -> SummaryOutcome:
    """Call the model only with failures. Ungrounded lines are replaced by the recorded results."""
    if not failures:
        raise UsageError("summarize_failures called with no failures.")
    warnings: list[str] = []
    try:
        raw = client.complete(system=SYSTEM_PROMPT, user=build_user_prompt(failures))
        parsed = parse_summary(raw)
    except (LLMError, SummaryParseError) as exc:
        warnings.append(
            "Summary used the recorded results because the model output could not be used: "
            f"{exc}"
        )
        return SummaryOutcome(text=render_recorded_summary(failures), source="recorded", warnings=warnings)

    kept, dropped = guard_summary(failures, parsed)
    warnings.extend(f"Dropped an ungrounded summary line: {reason}" for reason in dropped)
    if not kept:
        warnings.append("Summary used the recorded results because no model line matched the check results.")
        return SummaryOutcome(text=render_recorded_summary(failures), source="recorded", warnings=warnings)
    return SummaryOutcome(text=render_model_summary(kept), source="model", warnings=warnings)


def parse_summary(raw: str) -> LLMSummary:
    """Accept the object we asked for, or a bare array of bullets."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SummaryParseError("model output was not JSON.") from exc
    if isinstance(data, list):
        data = {"bullets": data}
    if not isinstance(data, dict):
        raise SummaryParseError("model output was not a JSON object.")
    try:
        return LLMSummary.model_validate(data)
    except ValidationError as exc:
        raise SummaryParseError("model output did not match the summary schema.") from exc
