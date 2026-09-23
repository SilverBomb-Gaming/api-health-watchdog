"""Config files are validated before any request is sent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api_watch.config import load_config
from api_watch.errors import UsageError

ROOT = Path(__file__).resolve().parents[1]


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_yaml_defaults_and_sample_files() -> None:
    loaded = load_config(ROOT / "samples" / "endpoints.yaml")
    assert [item.name for item in loaded.targets] == [
        "httpbin-ok",
        "httpbin-server-error",
        "httpbin-headers",
    ]
    assert loaded.targets[0].method == "GET"
    assert loaded.targets[0].expect_status == 200
    assert loaded.targets[0].timeout_seconds == 10
    assert loaded.targets[2].headers["X-Demo-Client"] == "api-watch"
    assert loaded.targets[2].headers["X-Request-Source"] == "local-demo"

    as_json = load_config(ROOT / "samples" / "endpoints.json")
    assert [item.url for item in as_json.targets] == [item.url for item in loaded.targets]
    local = load_config(ROOT / "samples" / "local.yaml")
    assert [item.name for item in local.targets] == ["local-ok", "local-fail", "local-slow"]
    assert local.targets[2].timeout_seconds == 1


def test_aliases_method_case_and_env_forms(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "targets.yml",
        """
targets:
  - name: billing
    url: https://example.test/health
    method: post
    expected_status: 204
    timeout: 2.5
    headers:
      Authorization: ${API_TOKEN}
      X-Env: env:REGION
      Accept: application/json
""",
    )
    loaded = load_config(path, env={"API_TOKEN": "secret-token", "REGION": "east"})
    target = loaded.targets[0]
    assert target.method == "POST"
    assert target.expect_status == 204
    assert target.timeout_seconds == 2.5
    assert target.headers["Authorization"] == "secret-token"
    assert target.headers["X-Env"] == "east"
    assert target.headers["Accept"] == "application/json"


def test_default_in_env_reference_is_used_when_unset(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "one.yaml",
        """
targets:
  - name: demo
    url: https://example.test/health
    headers:
      X-Source: ${API_WATCH_SOURCE:-local-demo}
""",
    )
    loaded = load_config(path, env={})
    assert loaded.targets[0].headers["X-Source"] == "local-demo"


def test_missing_env_var_is_a_config_error(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "one.yaml",
        """
targets:
  - name: demo
    url: https://example.test/health
    headers:
      Authorization: ${API_TOKEN}
""",
    )
    with pytest.raises(UsageError, match="API_TOKEN"):
        load_config(path, env={})


def test_literal_does_not_expand_a_partial_reference(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "one.yaml",
        """
targets:
  - name: demo
    url: https://example.test/health
    headers:
      Authorization: "Bearer ${API_TOKEN}"
""",
    )
    loaded = load_config(path, env={"API_TOKEN": "secret-token"})
    assert loaded.targets[0].headers["Authorization"] == "Bearer ${API_TOKEN}"


def test_rejects_bad_files(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(UsageError, match="not found"):
        load_config(missing)

    text = _write(tmp_path, "notes.txt", "targets: []\n")
    with pytest.raises(UsageError, match=".yaml"):
        load_config(text)

    broken = _write(tmp_path, "broken.json", "{")
    with pytest.raises(UsageError, match="JSON"):
        load_config(broken)

    bad_yaml = _write(tmp_path, "bad.yaml", "targets: [\n")
    with pytest.raises(UsageError, match="YAML"):
        load_config(bad_yaml)

    empty = _write(tmp_path, "empty.yaml", "targets: []\n")
    with pytest.raises(UsageError, match="at least one"):
        load_config(empty)

    root = _write(tmp_path, "root.yaml", "- https://example.test\n")
    with pytest.raises(UsageError, match="mapping"):
        load_config(root)


def test_rejects_invalid_targets(tmp_path: Path) -> None:
    cases = {
        "duplicate names": (
            """
targets:
  - name: demo
    url: https://example.test/a
  - name: demo
    url: https://example.test/b
""",
            "Duplicate target name",
        ),
        "method": (
            """
targets:
  - name: demo
    url: https://example.test/a
    method: TRACE
""",
            "method must be one of",
        ),
        "status": (
            """
targets:
  - name: demo
    url: https://example.test/a
    expect_status: 99
""",
            "expect_status",
        ),
        "timeout": (
            """
targets:
  - name: demo
    url: https://example.test/a
    timeout_seconds: 0
""",
            "timeout_seconds",
        ),
        "url": (
            """
targets:
  - name: demo
    url: /relative
""",
            "absolute http",
        ),
        "unknown": (
            """
targets:
  - name: demo
    url: https://example.test/a
    owner: someone
""",
            "owner",
        ),
        "both status keys": (
            """
targets:
  - name: demo
    url: https://example.test/a
    expect_status: 200
    expected_status: 201
""",
            "only one of expect_status",
        ),
        "header type": (
            """
targets:
  - name: demo
    url: https://example.test/a
    headers:
      X-Count: 3
""",
            "string",
        ),
    }
    for name, (body, match) in cases.items():
        path = _write(tmp_path, f"{name}.yaml", body)
        with pytest.raises(UsageError, match=match):
            load_config(path)


def test_unknown_root_field(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "extra.yaml",
        """
version: 1
targets:
  - name: demo
    url: https://example.test/health
""",
    )
    with pytest.raises(UsageError, match="Unknown config field: version"):
        load_config(path)


def test_json_round_trip_shape(tmp_path: Path) -> None:
    document = {
        "targets": [
            {"name": "demo", "url": "https://example.test/health"},
        ]
    }
    path = _write(tmp_path, "one.json", json.dumps(document))
    loaded = load_config(path)
    assert loaded.targets[0].method == "GET"
    assert loaded.targets[0].expect_status == 200
    assert loaded.targets[0].headers == {}
