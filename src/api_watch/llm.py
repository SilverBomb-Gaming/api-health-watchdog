"""Ollama and OpenAI-compatible chat clients.

The default provider is Ollama on localhost. No API key is required for that path.
The client is built only when --summarize is set and at least one check failed.
"""

from __future__ import annotations

import os
from typing import Protocol

import httpx

from api_watch.errors import LLMError

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_NUM_CTX = 8192


class LLMClient(Protocol):
    """Minimal chat client. Tests substitute their own object with this shape."""

    def complete(self, *, system: str, user: str) -> str:
        """Return the assistant message content."""

    def close(self) -> None:
        """Release owned HTTP resources."""


class OllamaClient:
    """Talk to Ollama's native /api/chat endpoint and request JSON output."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float,
        num_ctx: int,
        http: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self._http = http or httpx.Client(timeout=timeout)
        self._owns_http = http is None

    def complete(self, *, system: str, user: str) -> str:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "num_ctx": self.num_ctx,
                "num_predict": 1024,
            },
        }
        response = self._post(url, payload, headers=None)
        try:
            body = response.json()
        except ValueError as exc:
            raise LLMError("Ollama returned a response that was not JSON.") from exc
        message = body.get("message") if isinstance(body, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise LLMError("Ollama returned an empty message.")
        return content

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def _post(
        self,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str] | None,
    ) -> httpx.Response:
        try:
            response = self._http.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMError(
                f"Timed out waiting for the model at {self.base_url}. "
                "Raise API_WATCH_TIMEOUT if the model is still loading."
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMError(
                f"Could not reach Ollama at {self.base_url}. "
                f"Start Ollama and pull the model (`ollama pull {self.model}`)."
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Request to Ollama failed: {exc}") from exc
        if response.status_code >= 400:
            detail = response.text.strip().replace("\n", " ")[:400]
            hint = ""
            if response.status_code == 404:
                hint = f" If the model is missing, run `ollama pull {self.model}`."
            raise LLMError(f"Ollama returned HTTP {response.status_code}: {detail}.{hint}".rstrip())
        return response


class OpenAICompatibleClient:
    """POST /chat/completions on an OpenAI-compatible base URL."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        http: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._http = http or httpx.Client(timeout=timeout)
        self._owns_http = http is None

    def complete(self, *, system: str, user: str) -> str:
        url = _chat_completions_url(self.base_url)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, object] = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 1024,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        response = self._post(url, payload, headers)
        try:
            body = response.json()
        except ValueError as exc:
            raise LLMError("The OpenAI-compatible server returned a response that was not JSON.") from exc
        choices = body.get("choices") if isinstance(body, dict) else None
        if not isinstance(choices, list) or not choices:
            raise LLMError("The OpenAI-compatible server returned no choices.")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise LLMError("The OpenAI-compatible server returned an empty message.")
        return content

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def _post(self, url: str, payload: dict[str, object], headers: dict[str, str]) -> httpx.Response:
        try:
            response = self._http.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMError(
                f"Timed out waiting for the model at {self.base_url}. "
                "Raise API_WATCH_TIMEOUT if the model is still loading."
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMError(f"Could not reach the OpenAI-compatible server at {self.base_url}.") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Request to the OpenAI-compatible server failed: {exc}") from exc
        if response.status_code >= 400:
            detail = response.text.strip().replace("\n", " ")[:400]
            raise LLMError(f"OpenAI-compatible server returned HTTP {response.status_code}: {detail}.")
        return response


def build_client(provider: str | None = None, model: str | None = None) -> LLMClient:
    """Build the client selected by --provider or API_WATCH_PROVIDER. Default is Ollama."""
    selected = (provider or os.environ.get("API_WATCH_PROVIDER") or "ollama").strip().lower()
    timeout = _timeout_seconds()
    if selected == "ollama":
        return OllamaClient(
            base_url=os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
            model=(model or os.environ.get("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL).strip(),
            timeout=timeout,
            num_ctx=_num_ctx(),
        )
    if selected == "openai":
        base_url = os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL).strip()
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if "api.openai.com" in base_url and not api_key:
            raise LLMError(
                "OPENAI_API_KEY is required for api.openai.com. "
                "Set it, or leave API_WATCH_PROVIDER=ollama to summarize failures locally."
            )
        return OpenAICompatibleClient(
            base_url=base_url,
            api_key=api_key,
            model=(model or os.environ.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip(),
            timeout=timeout,
        )
    raise LLMError("API_WATCH_PROVIDER must be 'ollama' or 'openai'.")


def _timeout_seconds() -> float:
    raw = os.environ.get("API_WATCH_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS))
    try:
        value = float(raw)
    except ValueError as exc:
        raise LLMError("API_WATCH_TIMEOUT must be a number of seconds.") from exc
    if value <= 0:
        raise LLMError("API_WATCH_TIMEOUT must be positive.")
    return value


def _num_ctx() -> int:
    raw = os.environ.get("OLLAMA_NUM_CTX", str(DEFAULT_NUM_CTX))
    try:
        value = int(raw)
    except ValueError as exc:
        raise LLMError("OLLAMA_NUM_CTX must be an integer.") from exc
    if value < 1024:
        raise LLMError("OLLAMA_NUM_CTX must be at least 1024.")
    return value


def _chat_completions_url(base_url: str) -> str:
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"
