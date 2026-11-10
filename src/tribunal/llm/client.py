import json
import re
from collections import deque
from collections.abc import Sequence
from typing import Any, Protocol

import anthropic
import httpx

from tribunal.config import Settings

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str: ...


def extract_json(text: str) -> Any:
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char in "{[":
            try:
                value, _ = decoder.raw_decode(stripped[index:])
            except json.JSONDecodeError:
                continue
            return value
    raise LLMError("no JSON found in model output")


def complete_json(llm: LLMClient, system: str, user: str, *, max_tokens: int | None = None) -> Any:
    return extract_json(llm.complete(system, user, max_tokens=max_tokens))


class AnthropicClient:
    def __init__(self, api_key: str | None, model: str, max_tokens: int = 4096) -> None:
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    @classmethod
    def from_settings(cls, settings: Settings) -> "AnthropicClient":
        return cls(settings.anthropic_api_key, settings.llm_model, settings.llm_max_tokens)

    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens or self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.APIError as exc:
            raise LLMError(f"anthropic request failed: {exc}") from exc
        parts = [block.text for block in response.content if getattr(block, "type", "") == "text"]
        text = "".join(parts).strip()
        if not text:
            raise LLMError("empty response from model")
        return text


class OllamaClient:
    def __init__(
        self,
        host: str,
        model: str,
        *,
        max_tokens: int = 4096,
        num_ctx: int = 16384,
        timeout_s: int = 600,
        temperature: float = 0.0,
        json_mode: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        self._host = host.rstrip("/")
        self._model = model
        self._max_tokens = max_tokens
        self._num_ctx = num_ctx
        self._temperature = temperature
        self._json_mode = json_mode
        self._http = client or httpx.Client(base_url=self._host, timeout=timeout_s)

    @classmethod
    def from_settings(cls, settings: Settings) -> "OllamaClient":
        return cls(
            settings.ollama_host,
            settings.ollama_model,
            max_tokens=settings.llm_max_tokens,
            num_ctx=settings.ollama_num_ctx,
            timeout_s=settings.ollama_timeout_s,
            temperature=settings.llm_temperature,
        )

    def close(self) -> None:
        self._http.close()

    def ping(self) -> None:
        try:
            response = self._http.get("/api/tags", timeout=10)
            response.raise_for_status()
            models = response.json().get("models", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError(
                f"cannot reach Ollama at {self._host}: {exc}. Start it with `ollama serve`."
            ) from exc

        installed: set[str] = set()
        for entry in models:
            if isinstance(entry, dict):
                installed.update(str(entry[key]) for key in ("name", "model") if entry.get(key))
        wanted = {self._model} if ":" in self._model else {self._model, f"{self._model}:latest"}
        if not installed & wanted:
            raise LLMError(
                f"Ollama model {self._model!r} is not installed. "
                f"Run `ollama pull {self._model}` or set TRIBUNAL_OLLAMA_MODEL."
            )

    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {
                "num_ctx": self._num_ctx,
                "num_predict": max_tokens or self._max_tokens,
                "temperature": self._temperature,
            },
        }
        if self._json_mode:
            payload["format"] = "json"

        try:
            response = self._http.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:300]
            raise LLMError(f"ollama returned {exc.response.status_code}: {detail}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError(f"ollama request failed: {exc}") from exc

        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        text = THINK_BLOCK.sub("", content or "").strip()
        if not text:
            raise LLMError("empty response from model")
        return text


class ScriptedLLM:
    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = deque(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str:
        self.calls.append((system, user))
        if not self._responses:
            raise LLMError("scripted LLM has no responses left")
        return self._responses.popleft()


def make_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider == "ollama":
        return OllamaClient.from_settings(settings)
    return AnthropicClient.from_settings(settings)


def preflight(settings: Settings) -> None:
    if settings.llm_provider == "ollama":
        client = OllamaClient.from_settings(settings)
        try:
            client.ping()
        finally:
            client.close()
    elif not settings.anthropic_api_key:
        raise LLMError("ANTHROPIC_API_KEY is not set")
