"""Ollama is the default. The OpenAI-compatible path is opt-in and mocked."""

from __future__ import annotations

import json

import httpx
import pytest

from api_watch.errors import LLMError
from api_watch.llm import OpenAICompatibleClient, OllamaClient, build_client


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "API_WATCH_PROVIDER",
        "API_WATCH_TIMEOUT",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "OLLAMA_NUM_CTX",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_default_client_is_local_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    client = build_client()
    assert isinstance(client, OllamaClient)
    assert client.base_url == "http://127.0.0.1:11434"
    assert client.model == "llama3.2"
    client.close()


def test_ollama_complete_posts_json_chat() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "{\"bullets\": []}"}})

    client = OllamaClient(
        base_url="http://127.0.0.1:11434",
        model="llama3.2",
        timeout=5,
        num_ctx=8192,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    content = client.complete(system="system rules", user="failures")
    client.close()
    assert content == "{\"bullets\": []}"
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "llama3.2"
    assert body["format"] == "json"
    assert body["options"]["temperature"] == 0
    assert body["messages"][0] == {"role": "system", "content": "system rules"}
    assert body["messages"][1]["content"] == "failures"


def test_openai_compatible_client_sends_bearer_token() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "{\"bullets\": []}"}}]},
        )

    client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:1234/v1",
        api_key="test-key",
        model="local-model",
        timeout=5,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    content = client.complete(system="system rules", user="failures")
    client.close()
    assert content == "{\"bullets\": []}"
    assert captured["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    assert captured["auth"] == "Bearer test-key"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0
    assert body["model"] == "local-model"


def test_openai_without_a_key_omits_the_authorization_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in {key.lower() for key in request.headers}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{\"bullets\": []}"}}]},
        )

    client = OpenAICompatibleClient(
        base_url="http://127.0.0.1:1234/v1",
        api_key="",
        model="local-model",
        timeout=5,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.complete(system="s", user="u") == "{\"bullets\": []}"
    client.close()


def test_openai_provider_requires_a_key_for_api_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("API_WATCH_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        build_client()


def test_provider_model_and_timeout_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("API_WATCH_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("OPENAI_MODEL", "from-env")
    client = build_client(model="from-flag")
    assert isinstance(client, OpenAICompatibleClient)
    assert client.model == "from-flag"
    client.close()

    monkeypatch.setenv("API_WATCH_PROVIDER", "nope")
    with pytest.raises(LLMError, match="ollama' or 'openai"):
        build_client()

    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("API_WATCH_TIMEOUT", "0")
    with pytest.raises(LLMError, match="API_WATCH_TIMEOUT"):
        build_client()

    monkeypatch.setenv("API_WATCH_TIMEOUT", "30")
    monkeypatch.setenv("OLLAMA_NUM_CTX", "100")
    with pytest.raises(LLMError, match="OLLAMA_NUM_CTX"):
        build_client()


def test_ollama_connection_errors_do_not_leak_a_traceback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = OllamaClient(
        base_url="http://127.0.0.1:11434",
        model="llama3.2",
        timeout=1,
        num_ctx=8192,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(LLMError, match="Could not reach Ollama"):
        client.complete(system="s", user="u")
    client.close()


def test_ollama_http_error_is_an_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="model missing")

    client = OllamaClient(
        base_url="http://127.0.0.1:11434",
        model="llama3.2",
        timeout=1,
        num_ctx=8192,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(LLMError, match="ollama pull llama3.2"):
        client.complete(system="s", user="u")
    client.close()
