"""Human table, dry-run plan, and JSON for one run."""

from __future__ import annotations

import json

from api_watch.models import CheckResult, SummaryBullet, Target


def render_table(results: list[CheckResult], *, checked_at: str, config_path: str) -> str:
    """Fixed-width table. The measured columns are the source of truth."""
    rows: list[tuple[str, str, str, str, str]] = [
        ("NAME", "RESULT", "STATUS", "LATENCY", "DETAIL"),
    ]
    for item in results:
        rows.append(
            (
                item.name,
                "PASS" if item.ok else "FAIL",
                "-" if item.status_code is None else str(item.status_code),
                "-" if item.latency_ms is None else f"{item.latency_ms:.1f} ms",
                item.error or "",
            )
        )
    widths = [max(len(row[index]) for row in rows) for index in range(5)]
    lines = [f"{checked_at}  {config_path}"]
    for index, row in enumerate(rows):
        lines.append("  ".join(cell.ljust(widths[column]) for column, cell in enumerate(row)).rstrip())
        if index == 0:
            lines.append("  ".join("-" * widths[column] for column in range(5)).rstrip())
    return "\n".join(lines) + "\n"


def render_plan(targets: list[Target], *, config_path: str) -> str:
    """List the checks that would run. Header names only, never values."""
    lines = [f"Planned checks ({len(targets)}) from {config_path}"]
    for target in targets:
        headers = ", ".join(target.headers) if target.headers else "-"
        lines.append(
            f"- {target.name}  {target.method}  {target.url}  "
            f"expect {target.expect_status}  timeout {target.timeout_seconds:g}s  "
            f"headers: {headers}"
        )
    lines.append("Config ok. No requests sent.")
    return "\n".join(lines) + "\n"


def render_plan_payload(targets: list[Target], *, config_path: str) -> dict[str, object]:
    return {
        "dry_run": True,
        "config": config_path,
        "targets": [
            {
                "name": target.name,
                "method": target.method,
                "url": target.url,
                "expect_status": target.expect_status,
                "timeout_seconds": target.timeout_seconds,
                "header_names": list(target.headers),
            }
            for target in targets
        ],
    }


def render_recorded_summary(failures: list[CheckResult]) -> str:
    """Deterministic summary. Every number is copied from a check result."""
    noun = "failed check" if len(failures) == 1 else "failed checks"
    lines = [f"{len(failures)} {noun}."]
    for item in failures:
        status = "none" if item.status_code is None else str(item.status_code)
        if item.latency_ms is None:
            latency = "none"
        else:
            latency = f"{item.latency_ms:.1f} ms"
        detail = item.error or "failed"
        lines.append(
            f"- {item.name} {item.method} {item.url}: {detail} (status {status}, latency {latency})"
        )
    return "\n".join(lines) + "\n"


def render_model_summary(bullets: list[SummaryBullet]) -> str:
    return "\n".join(f"- {bullet.sentence}" for bullet in bullets) + "\n"


def dump_json(payload: dict[str, object], *, compact: bool) -> str:
    if compact:
        return json.dumps(payload, separators=(",", ":")) + "\n"
    return json.dumps(payload, indent=2) + "\n"
