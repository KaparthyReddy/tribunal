import json

import httpx
import pytest

from tribunal.config import Settings
from tribunal.llm import AnthropicClient, LLMError, OllamaClient, make_llm, preflight
from tribunal.pipeline import build_pipeline


def _client(handler, **kwargs) -> OllamaClient:
    http = httpx.Client(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(handler),
    )
    return OllamaClient("http://ollama.test", "m:1", client=http, **kwargs)


def _chat(content: str) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})


def test_complete_sends_expected_payload() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        captured.append(json.loads(request.content))
        return _chat('{"ok": true}')

    client = _client(handler, num_ctx=8192, temperature=0.1)
    assert client.complete("sys", "usr", max_tokens=99) == '{"ok": true}'

    payload = captured[0]
    assert payload["model"] == "m:1"
    assert payload["stream"] is False
    assert payload["format"] == "json"
    assert payload["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert payload["options"] == {"num_ctx": 8192, "num_predict": 99, "temperature": 0.1}


def test_json_mode_can_be_disabled() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _chat("plain text")

    _client(handler, json_mode=False).complete("s", "u")
    assert "format" not in captured[0]


def test_think_blocks_are_stripped() -> None:
    client = _client(lambda request: _chat('<think>reasoning\nmore</think>\n{"a": 1}'))
    assert client.complete("s", "u") == '{"a": 1}'


def test_http_error_becomes_llm_error() -> None:
    client = _client(lambda request: httpx.Response(500, text="model crashed"))
    with pytest.raises(LLMError, match="500"):
        client.complete("s", "u")


def test_connection_error_becomes_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMError):
        _client(handler).complete("s", "u")


def test_empty_response_is_an_error() -> None:
    with pytest.raises(LLMError, match="empty"):
        _client(lambda request: _chat("   ")).complete("s", "u")
    with pytest.raises(LLMError):
        _client(lambda request: httpx.Response(200, json={})).complete("s", "u")


def test_ping_ok() -> None:
    client = _client(
        lambda request: httpx.Response(200, json={"models": [{"name": "m:1", "model": "m:1"}]})
    )
    client.ping()


def test_ping_missing_model() -> None:
    client = _client(lambda request: httpx.Response(200, json={"models": [{"name": "other:2"}]}))
    with pytest.raises(LLMError, match="ollama pull"):
        client.ping()


def test_ping_accepts_latest_tag_for_bare_names() -> None:
    http = httpx.Client(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"models": [{"name": "llama3:latest"}]})
        ),
    )
    OllamaClient("http://ollama.test", "llama3", client=http).ping()


def test_ping_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMError, match="ollama serve"):
        _client(handler).ping()


def test_make_llm_selects_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TRIBUNAL_ANTHROPIC_API_KEY", raising=False)

    local = make_llm(Settings(_env_file=None, llm_provider="ollama"))
    assert isinstance(local, OllamaClient)

    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        make_llm(Settings(_env_file=None, llm_provider="anthropic"))


def test_anthropic_client_requires_key() -> None:
    with pytest.raises(LLMError):
        AnthropicClient(None, "model")


def test_preflight_anthropic_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TRIBUNAL_ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError):
        preflight(Settings(_env_file=None, llm_provider="anthropic"))


def test_build_pipeline_runs_preflight(
    tmp_path, make_runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TRIBUNAL_ANTHROPIC_API_KEY", raising=False)
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", llm_provider="anthropic")
    pipe = build_pipeline(settings, runner=make_runner(lambda workdir, argv: (0, "", "")))
    assert pipe.prepare is not None
    with pytest.raises(LLMError):
        pipe.prepare()
