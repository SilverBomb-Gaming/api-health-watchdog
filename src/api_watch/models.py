"""Targets, check results, and the summary object requested from the model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Target(BaseModel):
    """One HTTP check. Header values are already resolved from the environment."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    method: str = "GET"
    expect_status: int = 200
    timeout_seconds: float = 10.0
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("method", mode="before")
    @classmethod
    def _normalize_method(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip().upper()

    @field_validator("headers", mode="before")
    @classmethod
    def _headers(cls, value: object) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("headers must be a mapping of names to strings.")
        cleaned: dict[str, str] = {}
        for key, raw in value.items():
            name = str(key).strip()
            if not name or any(char in name for char in "\r\n:"):
                raise ValueError(f"invalid header name: {key!r}")
            if not isinstance(raw, str):
                raise ValueError(f"header {name} must be a string.")
            cleaned[name] = raw
        return cleaned


class CheckResult(BaseModel):
    """One measured check. Fields stay null when the probe did not observe them."""

    model_config = ConfigDict(extra="forbid")

    name: str
    url: str
    method: str
    ok: bool
    expected_status: int
    status_code: int | None = None
    latency_ms: float | None = None
    error: str | None = None


class SummaryBullet(BaseModel):
    """One sentence from the model. Extra keys are ignored."""

    model_config = ConfigDict(extra="ignore")

    name: str = ""
    sentence: str = ""

    @field_validator("name", "sentence", mode="before")
    @classmethod
    def _strip(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


class LLMSummary(BaseModel):
    """JSON object requested from the model."""

    model_config = ConfigDict(extra="ignore")

    bullets: list[SummaryBullet] = Field(default_factory=list)

    @field_validator("bullets", mode="before")
    @classmethod
    def _coerce_list(cls, value: object) -> list[object]:
        if value is None:
            return []
        if isinstance(value, dict):
            return [value]
        if not isinstance(value, list):
            raise ValueError("expected a list.")
        return value
