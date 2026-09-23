"""A local .env fills unset variables and does not override the environment."""

from __future__ import annotations

import os
from pathlib import Path

from api_watch.dotenv import load_dotenv


def test_dotenv_sets_missing_values_and_strips_quotes(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "API_WATCH_PROVIDER=ollama",
                "OPENAI_API_KEY=\"from-file\"",
                "OLLAMA_MODEL='llama3.2'",
                "not a pair",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("API_WATCH_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.setenv("API_WATCH_PROVIDER", "already")
    load_dotenv(env_file)
    assert os.environ["API_WATCH_PROVIDER"] == "already"
    assert os.environ["OPENAI_API_KEY"] == "from-file"
    assert os.environ["OLLAMA_MODEL"] == "llama3.2"


def test_missing_dotenv_is_ignored(tmp_path: Path) -> None:
    load_dotenv(tmp_path / ".env")
