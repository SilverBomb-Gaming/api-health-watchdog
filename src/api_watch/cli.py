"""Command-line interface for api-watch."""

from __future__ import annotations

import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import typer

from api_watch import __version__
from api_watch.alert import format_alerts, post_webhook
from api_watch.checker import run_checks
from api_watch.config import load_config
from api_watch.dotenv import load_dotenv
from api_watch.errors import AlertError, LLMError, UsageError
from api_watch.llm import build_client
from api_watch.models import CheckResult
from api_watch.render import (
    dump_json,
    render_plan,
    render_plan_payload,
    render_recorded_summary,
    render_table,
)
from api_watch.store import DEFAULT_RESULTS_PATH, save_results
from api_watch.summarize import SummaryOutcome, summarize_failures

app = typer.Typer(
    name="api-watch",
    help="Watch HTTP endpoints and alert when a check fails.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"api-watch {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Watch HTTP endpoints and alert when a check fails."""


@app.command("check")
def check_cmd(
    config: Annotated[Path, typer.Option("--config", help="YAML or JSON file of targets.")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print the run as JSON instead of a table."),
    ] = False,
    summarize: Annotated[
        bool,
        typer.Option(
            "--summarize",
            help="After failures, ask Ollama for a summary. Skipped when every check passes.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate the config and print the planned checks. No network."),
    ] = False,
    results: Annotated[
        Optional[Path],
        typer.Option("--results", help="Write the last run JSON here. Default: .api-watch/last-results.json"),
    ] = None,
    no_save: Annotated[
        bool,
        typer.Option("--no-save", help="Do not write a results file."),
    ] = False,
    provider: Annotated[
        Optional[str],
        typer.Option("--provider", help="ollama (default) or openai. Used only with --summarize."),
    ] = None,
    model: Annotated[
        Optional[str],
        typer.Option("--model", help="Model name for --summarize. Overrides OLLAMA_MODEL or OPENAI_MODEL."),
    ] = None,
) -> None:
    """Run every target once. Exit 1 if any check fails."""
    try:
        code = execute(
            config_path=config,
            json_output=json_output,
            summarize=summarize,
            dry_run=dry_run,
            results=results,
            no_save=no_save,
            provider=provider,
            model=model,
            compact_json=False,
        )
    except UsageError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    raise typer.Exit(code)


@app.command("watch")
def watch_cmd(
    config: Annotated[Path, typer.Option("--config", help="YAML or JSON file of targets.")],
    interval: Annotated[float, typer.Option("--interval", help="Seconds to wait between runs.")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print one JSON object per run."),
    ] = False,
    summarize: Annotated[
        bool,
        typer.Option(
            "--summarize",
            help="After failures, ask Ollama for a summary. Skipped when every check passes.",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Validate the config and print the planned checks. Do not loop."),
    ] = False,
    results: Annotated[
        Optional[Path],
        typer.Option("--results", help="Write the last run JSON here. Default: .api-watch/last-results.json"),
    ] = None,
    no_save: Annotated[
        bool,
        typer.Option("--no-save", help="Do not write a results file."),
    ] = False,
    provider: Annotated[
        Optional[str],
        typer.Option("--provider", help="ollama (default) or openai. Used only with --summarize."),
    ] = None,
    model: Annotated[
        Optional[str],
        typer.Option("--model", help="Model name for --summarize. Overrides OLLAMA_MODEL or OPENAI_MODEL."),
    ] = None,
) -> None:
    """Run every target on a loop. Ctrl+C stops the loop and exits 0."""
    try:
        if not math.isfinite(interval) or interval <= 0:
            raise UsageError("--interval must be a positive number of seconds.")
        if dry_run:
            code = execute(
                config_path=config,
                json_output=json_output,
                summarize=summarize,
                dry_run=True,
                results=results,
                no_save=no_save,
                provider=provider,
                model=model,
                compact_json=False,
            )
            raise typer.Exit(code)
        started = False
        cycle = 0
        try:
            while True:
                if cycle and not json_output:
                    typer.echo("")
                try:
                    execute(
                        config_path=config,
                        json_output=json_output,
                        summarize=summarize,
                        dry_run=False,
                        results=results,
                        no_save=no_save,
                        provider=provider,
                        model=model,
                        compact_json=json_output,
                    )
                    started = True
                except UsageError as exc:
                    if not started:
                        raise
                    typer.secho(str(exc), fg=typer.colors.RED, err=True)
                cycle += 1
                time.sleep(interval)
        except KeyboardInterrupt:
            typer.echo("Stopped.", err=True)
            raise typer.Exit(0) from None
    except UsageError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc


def execute(
    *,
    config_path: Path,
    json_output: bool,
    summarize: bool,
    dry_run: bool,
    results: Path | None,
    no_save: bool,
    provider: str | None,
    model: str | None,
    compact_json: bool,
) -> int:
    """Load config, optionally probe, print, save, and alert. Returns 0 or 1."""
    if no_save and results is not None:
        raise UsageError("Use either --results or --no-save.")
    load_dotenv()
    loaded = load_config(config_path)
    if dry_run:
        if json_output:
            payload = render_plan_payload(loaded.targets, config_path=loaded.path)
            typer.echo(dump_json(payload, compact=False), nl=False)
        else:
            typer.echo(render_plan(loaded.targets, config_path=loaded.path), nl=False)
        return 0

    checked_at = _utc_now()
    check_results = run_checks(loaded.targets)
    failures = [item for item in check_results if not item.ok]
    outcome = _maybe_summarize(failures, summarize=summarize, provider=provider, model=model)
    results_path = None if no_save else (results if results is not None else DEFAULT_RESULTS_PATH)
    payload = _payload(
        checked_at=checked_at,
        config_path=loaded.path,
        results=check_results,
        outcome=outcome,
        results_path=None if results_path is None else str(results_path),
    )
    if results_path is not None:
        save_results(results_path, payload)
        typer.echo(f"Saved {results_path}.", err=True)

    if json_output:
        typer.echo(dump_json(payload, compact=compact_json), nl=False)
    else:
        typer.echo(render_table(check_results, checked_at=checked_at, config_path=loaded.path), nl=False)
        if outcome is not None and outcome.source != "skipped":
            typer.echo("\nSummary:\n", nl=False)
            typer.echo(outcome.text, nl=False)

    if failures:
        typer.secho(format_alerts(failures), fg=typer.colors.RED, err=True)
        _send_webhook(payload)
        return 1
    return 0


def _maybe_summarize(
    failures: list[CheckResult],
    *,
    summarize: bool,
    provider: str | None,
    model: str | None,
) -> SummaryOutcome | None:
    if not summarize:
        return None
    if not failures:
        typer.echo("No failures; skipped summary.", err=True)
        return SummaryOutcome(text="", source="skipped", warnings=[])
    try:
        client = build_client(provider, model)
    except LLMError as exc:
        warning = f"Summary used the recorded results because the model could not be reached: {exc}"
        typer.echo(f"warning: {warning}", err=True)
        return SummaryOutcome(text=render_recorded_summary(failures), source="recorded", warnings=[warning])
    try:
        outcome = summarize_failures(failures, client)
    finally:
        client.close()
    for warning in outcome.warnings:
        typer.echo(f"warning: {warning}", err=True)
    return outcome


def _send_webhook(payload: dict[str, object]) -> None:
    webhook = os.environ.get("API_WATCH_WEBHOOK_URL", "").strip()
    if not webhook:
        return
    try:
        post_webhook(webhook, payload)
    except AlertError as exc:
        typer.echo(f"warning: {exc}", err=True)


def _payload(
    *,
    checked_at: str,
    config_path: str,
    results: list[CheckResult],
    outcome: SummaryOutcome | None,
    results_path: str | None,
) -> dict[str, object]:
    failures = [item for item in results if not item.ok]
    payload: dict[str, object] = {
        "checked_at": checked_at,
        "config": config_path,
        "ok": not failures,
        "failure_count": len(failures),
        "results": [item.model_dump() for item in results],
    }
    if outcome is not None:
        payload["summary"] = outcome.text if outcome.source != "skipped" else None
        payload["summary_source"] = outcome.source
    if results_path is not None:
        payload["results_path"] = results_path
    return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
