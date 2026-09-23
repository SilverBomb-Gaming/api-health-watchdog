"""CLI paths that must work with no Ollama process and no real network."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from api_watch.cli import app

ROOT = Path(__file__).resolve().parents[1]
RUNNER = CliRunner()


def _write(tmp_path: Path, body: str, name: str = "targets.yaml") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _patch_http(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    import api_watch.checker as checker

    real = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(checker.httpx, "Client", factory)


def test_version() -> None:
    result = RUNNER.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "api-watch 0.1.0" in result.stdout


def test_help_lists_the_commands() -> None:
    result = RUNNER.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "check" in result.stdout
    assert "watch" in result.stdout
    check = RUNNER.invoke(app, ["check", "--help"])
    assert check.exit_code == 0
    for flag in ("--config", "--json", "--summarize", "--dry-run", "--no-save"):
        assert flag in check.stdout
    watch = RUNNER.invoke(app, ["watch", "--help"])
    assert "--interval" in watch.stdout


def test_missing_config_is_usage() -> None:
    result = RUNNER.invoke(app, ["check"])
    assert result.exit_code == 2


def test_sample_dry_run_sends_no_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("dry-run must not open an HTTP client")

    monkeypatch.setattr("api_watch.checker.httpx.Client", fail)
    monkeypatch.setattr("api_watch.cli.build_client", fail)
    result = RUNNER.invoke(
        app,
        ["check", "--config", str(ROOT / "samples" / "endpoints.yaml"), "--dry-run"],
    )
    assert result.exit_code == 0, result.stderr
    assert "Planned checks (3) from" in result.stdout
    assert "httpbin-ok" in result.stdout
    assert "httpbin-server-error" in result.stdout
    assert "headers: X-Demo-Client, X-Request-Source" in result.stdout
    assert "No requests sent." in result.stdout
    assert "local-demo" not in result.stdout
    assert "secret" not in result.stdout


def test_sample_json_dry_run() -> None:
    result = RUNNER.invoke(
        app,
        ["check", "--config", str(ROOT / "samples" / "endpoints.json"), "--dry-run", "--json"],
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["targets"][2]["header_names"] == ["X-Demo-Client", "X-Request-Source"]
    assert "local-demo" not in result.stdout


def test_bad_config_exits_2(tmp_path: Path) -> None:
    path = _write(tmp_path, "targets: []\n")
    result = RUNNER.invoke(app, ["check", "--config", str(path), "--no-save"])
    assert result.exit_code == 2
    assert "at least one" in result.stderr


def test_check_exit_codes_and_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/down"):
            return httpx.Response(500)
        return httpx.Response(200)

    _patch_http(monkeypatch, handler)
    path = _write(
        tmp_path,
        """
targets:
  - name: ok
    url: https://example.test/ok
  - name: down
    url: https://example.test/down
""",
    )
    ok_path = _write(
        tmp_path,
        """
targets:
  - name: ok
    url: https://example.test/ok
""",
        name="ok.yaml",
    )
    passed = RUNNER.invoke(app, ["check", "--config", str(ok_path), "--no-save"])
    assert passed.exit_code == 0, passed.stderr
    assert "PASS" in passed.stdout
    assert "ALERT" not in passed.stderr

    failed = RUNNER.invoke(app, ["check", "--config", str(path), "--json"])
    assert failed.exit_code == 1
    payload = json.loads(failed.stdout)
    assert payload["ok"] is False
    assert payload["failure_count"] == 1
    assert payload["results"][1]["status_code"] == 500
    assert payload["results"][1]["error"] == "expected status 200, got 500"
    assert "summary" not in payload
    assert "ALERT down: expected status 200, got 500" in failed.stderr
    saved = json.loads((tmp_path / ".api-watch" / "last-results.json").read_text(encoding="utf-8"))
    assert saved["results"][1]["name"] == "down"
    assert "Saved" in failed.stderr


def test_results_flag_and_no_save_conflict(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
targets:
  - name: ok
    url: https://example.test/ok
""",
    )
    result = RUNNER.invoke(
        app,
        ["check", "--config", str(path), "--dry-run", "--no-save", "--results", str(tmp_path / "out.json")],
    )
    assert result.exit_code == 2
    assert "--results" in result.stderr


def test_dry_run_does_not_write_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    path = _write(
        tmp_path,
        """
targets:
  - name: ok
    url: https://example.test/ok
""",
    )
    result = RUNNER.invoke(app, ["check", "--config", str(path), "--dry-run"])
    assert result.exit_code == 0
    assert not (tmp_path / ".api-watch").exists()


def test_header_secret_is_not_printed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "super-secret"
        return httpx.Response(200)

    _patch_http(monkeypatch, handler)
    path = _write(
        tmp_path,
        """
targets:
  - name: ok
    url: https://example.test/ok
    headers:
      Authorization: super-secret
""",
    )
    destination = tmp_path / "last.json"
    result = RUNNER.invoke(
        app,
        ["check", "--config", str(path), "--results", str(destination)],
    )
    assert result.exit_code == 0, result.stderr
    blob = result.stdout + result.stderr + destination.read_text(encoding="utf-8")
    assert "super-secret" not in blob


def test_summarize_is_skipped_when_every_check_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    def fail(*args, **kwargs):
        raise AssertionError("a passing run must not build a model client")

    _patch_http(monkeypatch, handler)
    monkeypatch.setattr("api_watch.cli.build_client", fail)
    path = _write(
        tmp_path,
        """
targets:
  - name: ok
    url: https://example.test/ok
""",
    )
    result = RUNNER.invoke(app, ["check", "--config", str(path), "--summarize", "--no-save", "--json"])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary"] is None
    assert payload["summary_source"] == "skipped"
    assert "No failures; skipped summary." in result.stderr
    assert "Summary:" not in result.stdout


def test_summarize_drops_invented_facts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    class Fake:
        def complete(self, *, system: str, user: str) -> str:
            assert "Do not invent endpoints" in system
            assert "https://example.test/health" in user
            assert "https://example.test/other" not in user
            data = json.loads(user.strip().split("\n\n", 1)[1])
            assert data[0]["status_code"] == 503
            return json.dumps(
                {
                    "bullets": [
                        {
                            "name": "billing",
                            "sentence": "billing at https://evil.test returned status 404 in 999 ms.",
                        }
                    ]
                }
            )

        def close(self) -> None:
            return None

    _patch_http(monkeypatch, handler)
    monkeypatch.setattr("api_watch.cli.build_client", lambda provider, model: Fake())
    path = _write(
        tmp_path,
        """
targets:
  - name: billing
    url: https://example.test/health
  - name: other
    url: https://example.test/other
""",
    )
    # The second target also returns 503 via the handler. Give it a pass by path.
    def mixed(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/other"):
            return httpx.Response(200)
        return httpx.Response(503)

    _patch_http(monkeypatch, mixed)
    result = RUNNER.invoke(
        app,
        ["check", "--config", str(path), "--summarize", "--no-save"],
    )
    assert result.exit_code == 1, result.stderr
    assert "https://example.test/health" in result.stdout
    assert "https://evil.test" not in result.stdout
    assert "404" not in result.stdout
    assert "999" not in result.stdout
    assert "Summary:" in result.stdout
    assert "Dropped an ungrounded summary line" in result.stderr


def test_summarize_prints_a_grounded_sentence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    class Fake:
        def complete(self, *, system: str, user: str) -> str:
            data = json.loads(user.strip().split("\n\n", 1)[1])
            item = data[0]
            sentence = (
                f"{item['name']} returned status {item['status_code']} in {item['latency_ms']} ms."
            )
            return json.dumps({"bullets": [{"name": item["name"], "sentence": sentence}]})

        def close(self) -> None:
            return None

    _patch_http(monkeypatch, handler)
    monkeypatch.setattr("api_watch.cli.build_client", lambda provider, model: Fake())
    path = _write(
        tmp_path,
        """
targets:
  - name: billing
    url: https://example.test/health
""",
    )
    result = RUNNER.invoke(
        app,
        ["check", "--config", str(path), "--summarize", "--no-save", "--json"],
    )
    assert result.exit_code == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["summary_source"] == "model"
    assert "status 503" in payload["summary"]
    latency = payload["results"][0]["latency_ms"]
    assert f"{latency} ms" in payload["summary"]
    assert "warning:" not in result.stderr


def test_webhook_posts_only_when_a_check_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/down"):
            return httpx.Response(500)
        return httpx.Response(200)

    def capture(url: str, payload: dict[str, object], **kwargs: object) -> None:
        calls.append({"url": url, "payload": payload})

    _patch_http(monkeypatch, handler)
    monkeypatch.setenv("API_WATCH_WEBHOOK_URL", "https://hooks.example.test/alerts")
    monkeypatch.setattr("api_watch.cli.post_webhook", capture)
    ok_path = _write(
        tmp_path,
        """
targets:
  - name: ok
    url: https://example.test/ok
""",
        name="ok.yaml",
    )
    ok = RUNNER.invoke(app, ["check", "--config", str(ok_path), "--no-save"])
    assert ok.exit_code == 0
    assert calls == []

    bad_path = _write(
        tmp_path,
        """
targets:
  - name: down
    url: https://example.test/down
""",
        name="down.yaml",
    )
    bad = RUNNER.invoke(app, ["check", "--config", str(bad_path), "--no-save", "--json"])
    assert bad.exit_code == 1
    assert calls[0]["url"] == "https://hooks.example.test/alerts"
    posted = calls[0]["payload"]
    assert isinstance(posted, dict)
    assert posted["failure_count"] == 1
    assert posted["results"][0]["status_code"] == 500


def test_webhook_failure_does_not_replace_the_check_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api_watch.errors import AlertError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    def boom(url: str, payload: dict[str, object], **kwargs: object) -> None:
        raise AlertError("Webhook returned HTTP 500: nope")

    _patch_http(monkeypatch, handler)
    monkeypatch.setenv("API_WATCH_WEBHOOK_URL", "https://hooks.example.test/alerts")
    monkeypatch.setattr("api_watch.cli.post_webhook", boom)
    path = _write(
        tmp_path,
        """
targets:
  - name: down
    url: https://example.test/down
""",
    )
    result = RUNNER.invoke(app, ["check", "--config", str(path), "--no-save"])
    assert result.exit_code == 1
    assert "Webhook returned HTTP 500" in result.stderr
    assert "ALERT down" in result.stderr


def test_watch_stops_on_ctrl_c(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    def stop(_interval: float) -> None:
        raise KeyboardInterrupt

    _patch_http(monkeypatch, handler)
    monkeypatch.setattr("api_watch.cli.time.sleep", stop)
    path = _write(
        tmp_path,
        """
targets:
  - name: down
    url: https://example.test/down
""",
    )
    result = RUNNER.invoke(
        app,
        ["watch", "--config", str(path), "--interval", "5", "--no-save"],
    )
    assert result.exit_code == 0, result.stderr
    assert "FAIL" in result.stdout
    assert "ALERT down" in result.stderr
    assert "Stopped." in result.stderr


def test_watch_rejects_a_bad_interval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    slept = {"called": False}

    def stop(_interval: float) -> None:
        slept["called"] = True
        raise KeyboardInterrupt

    monkeypatch.setattr("api_watch.cli.time.sleep", stop)
    path = _write(
        tmp_path,
        """
targets:
  - name: ok
    url: https://example.test/ok
""",
    )
    result = RUNNER.invoke(app, ["watch", "--config", str(path), "--interval", "0", "--dry-run"])
    assert result.exit_code == 2
    assert "--interval" in result.stderr
    assert slept["called"] is False


def test_watch_dry_run_does_not_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def stop(_interval: float) -> None:
        raise AssertionError("dry-run must not sleep")

    monkeypatch.setattr("api_watch.cli.time.sleep", stop)
    path = _write(
        tmp_path,
        """
targets:
  - name: ok
    url: https://example.test/ok
""",
    )
    result = RUNNER.invoke(app, ["watch", "--config", str(path), "--interval", "5", "--dry-run"])
    assert result.exit_code == 0, result.stderr
    assert "No requests sent." in result.stdout
