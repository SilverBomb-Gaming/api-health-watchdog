"""Prompts for the optional failure summary.

The system prompt states the rule. The program also drops any line that cites an
endpoint, status code, or latency this run did not record.
"""

from __future__ import annotations

import json

from api_watch.models import CheckResult

SYSTEM_PROMPT = """You summarize failed HTTP health checks. The user message is a JSON array of check results this program recorded.

Rules:
- Do not invent endpoints, status codes, or latencies that are not present in the check results.
- Do not add a target that is not in the JSON.
- Every bullet name must be copied from a name in the JSON.
- If status_code is null, do not invent a status code.
- If latency_ms is null, do not invent a latency.
- When you mention a status code, copy expected_status or status_code from that same object.
- When you mention a latency, copy latency_ms from that same object and write it as milliseconds with the suffix ms.
- When you mention an endpoint, copy url from that same object.
- Do not explain a cause, an owner, or a fix that the JSON does not state.
- Return a JSON object with one key, bullets. Each bullet has name and sentence.
- One bullet per failed check. If you cannot stay inside these rules, return {"bullets": []}.
"""


def build_user_prompt(failures: list[CheckResult]) -> str:
    """Embed only the failed checks. Passing checks are not sent to the model."""
    payload = json.dumps([item.model_dump() for item in failures], indent=2)
    return (
        "Summarize these failed health checks.\n"
        "Do not invent endpoints, status codes, or latencies that are not present in the check results.\n"
        "Return a JSON object: {\"bullets\": [{\"name\": \"...\", \"sentence\": \"...\"}]}.\n"
        "Copy name, url, status_code, and latency_ms from the JSON when you mention them.\n\n"
        f"{payload}\n"
    )
