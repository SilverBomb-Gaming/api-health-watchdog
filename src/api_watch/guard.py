"""Drop summary lines that cite facts this run did not record."""

from __future__ import annotations

import re

from api_watch.models import CheckResult, LLMSummary, SummaryBullet

_URL = re.compile(r"https?://[^\s<>\"')\]]+")
_LATENCY = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:ms|milliseconds)\b", re.IGNORECASE)
_STATUS = re.compile(r"(?<!\d)([1-5]\d{2})(?!\d)")
_TRAILING = ".,;:"


def guard_summary(
    failures: list[CheckResult],
    summary: LLMSummary,
) -> tuple[list[SummaryBullet], list[str]]:
    """Keep a bullet only when its name, URLs, status codes, and latencies match one failure."""
    by_name = {item.name: item for item in failures}
    kept: list[SummaryBullet] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for bullet in summary.bullets:
        name = bullet.name.strip()
        if not name or name not in by_name:
            dropped.append(f"{name or '(blank)'}: not a failed check in this run")
            continue
        if name in seen:
            dropped.append(f"{name}: repeated target")
            continue
        if not bullet.sentence.strip():
            dropped.append(f"{name}: empty sentence")
            continue
        reason = _ungrounded(bullet.sentence, by_name[name])
        if reason is not None:
            dropped.append(f"{name}: {reason}")
            continue
        seen.add(name)
        kept.append(SummaryBullet(name=name, sentence=bullet.sentence.strip()))
    return kept, dropped


def _ungrounded(sentence: str, result: CheckResult) -> str | None:
    for raw_url in _URL.findall(sentence):
        url = raw_url.rstrip(_TRAILING)
        if url != result.url:
            return f"endpoint {url} is not in the check result"
    allowed_status = {result.expected_status}
    if result.status_code is not None:
        allowed_status.add(result.status_code)
    for token in _STATUS.findall(_LATENCY.sub(" ", sentence)):
        code = int(token)
        if code not in allowed_status:
            return f"status code {code} is not in the check result"
    latencies = [float(match) for match in _LATENCY.findall(sentence)]
    if result.latency_ms is None:
        if latencies:
            return "latency was not recorded for this check"
        return None
    for value in latencies:
        if not _latency_matches(value, result.latency_ms):
            return f"latency {value:g} ms is not in the check result"
    return None


def _latency_matches(value: float, recorded: float) -> bool:
    return abs(value - recorded) <= 0.05 or abs(value - round(recorded, 1)) <= 0.05
