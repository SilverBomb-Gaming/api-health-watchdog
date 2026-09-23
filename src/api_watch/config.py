"""Load a YAML or JSON target list. Secrets stay in the environment."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from api_watch.errors import UsageError
from api_watch.models import Target

_ALLOWED_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
_ENV_BRACES = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}$")
_ENV_PREFIX = re.compile(r"^env:([A-Za-z_][A-Za-z0-9_]*)$")


class LoadedConfig(BaseModel):
    """Targets ready to run. Header values are resolved and are not for display."""

    model_config = ConfigDict(extra="forbid")

    path: str
    targets: list[Target] = Field(min_length=1)


def load_config(path: Path, *, env: Mapping[str, str] | None = None) -> LoadedConfig:
    """Read a config file and resolve header values that are environment references."""
    source = Path(path)
    raw = _read_raw(source)
    if not isinstance(raw, dict):
        raise UsageError("Config must be a mapping with a targets list.")
    unknown = sorted(set(raw) - {"targets"})
    if unknown:
        raise UsageError(f"Unknown config field: {', '.join(unknown)}.")
    targets_raw = raw.get("targets")
    if not isinstance(targets_raw, list):
        raise UsageError("Config must include a targets list.")
    if not targets_raw:
        raise UsageError("Config must include at least one target.")

    normalized = [_normalize_target(item, index) for index, item in enumerate(targets_raw)]
    try:
        targets = [Target.model_validate(item) for item in normalized]
    except ValidationError as exc:
        raise UsageError(f"Invalid config: {_format_validation(exc)}") from exc

    _validate_targets(targets)
    resolved = [_resolve_headers(target, os.environ if env is None else env) for target in targets]
    return LoadedConfig(path=str(source), targets=resolved)


def _read_raw(source: Path) -> object:
    if not source.is_file():
        raise UsageError(f"Config file not found: {source}")
    suffix = source.suffix.casefold()
    text = source.read_text(encoding="utf-8")
    if suffix in {".yaml", ".yml"}:
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise UsageError(f"Could not parse YAML: {exc}") from exc
    if suffix == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise UsageError(f"Could not parse JSON: {exc}") from exc
    raise UsageError("Config file must be .yaml, .yml, or .json.")


def _normalize_target(item: object, index: int) -> dict[str, object]:
    if not isinstance(item, dict):
        raise UsageError(f"targets[{index}] must be a mapping.")
    data = dict(item)
    if "expected_status" in data and "expect_status" in data:
        raise UsageError(f"targets[{index}] must use only one of expect_status or expected_status.")
    if "expected_status" in data:
        data["expect_status"] = data.pop("expected_status")
    if "timeout" in data and "timeout_seconds" in data:
        raise UsageError(f"targets[{index}] must use only one of timeout_seconds or timeout.")
    if "timeout" in data:
        data["timeout_seconds"] = data.pop("timeout")
    return data


def _validate_targets(targets: list[Target]) -> None:
    seen: set[str] = set()
    for target in targets:
        if target.name in seen:
            raise UsageError(f"Duplicate target name: {target.name}")
        seen.add(target.name)
        if target.method not in _ALLOWED_METHODS:
            allowed = ", ".join(sorted(_ALLOWED_METHODS))
            raise UsageError(f"{target.name}: method must be one of {allowed}.")
        if not isinstance(target.expect_status, int) or isinstance(target.expect_status, bool):
            raise UsageError(f"{target.name}: expect_status must be an integer from 100 to 599.")
        if not 100 <= target.expect_status <= 599:
            raise UsageError(f"{target.name}: expect_status must be an integer from 100 to 599.")
        if target.timeout_seconds <= 0:
            raise UsageError(f"{target.name}: timeout_seconds must be positive.")
        parsed = urlparse(target.url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise UsageError(f"{target.name}: url must be an absolute http or https URL.")


def _resolve_headers(target: Target, env: Mapping[str, str]) -> Target:
    resolved: dict[str, str] = {}
    for name, raw in target.headers.items():
        resolved[name] = _resolve_header_value(target.name, name, raw, env)
    return target.model_copy(update={"url": target.url.strip(), "headers": resolved})


def _resolve_header_value(target_name: str, header_name: str, raw: str, env: Mapping[str, str]) -> str:
    """Resolve a header only when the whole value is an environment reference."""
    braces = _ENV_BRACES.fullmatch(raw.strip())
    if braces:
        var_name, default = braces.group(1), braces.group(2)
        if var_name in env:
            return env[var_name]
        if default is not None:
            return default
        raise UsageError(
            f"{target_name}: header {header_name} references unset environment variable {var_name}."
        )
    prefixed = _ENV_PREFIX.fullmatch(raw.strip())
    if prefixed:
        var_name = prefixed.group(1)
        if var_name not in env:
            raise UsageError(
                f"{target_name}: header {header_name} references unset environment variable {var_name}."
            )
        return env[var_name]
    return raw


def _format_validation(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        loc = ".".join(str(item) for item in error["loc"])
        parts.append(f"{loc}: {error['msg']}")
    return "; ".join(parts)
