import json
import re
from collections import deque
from collections.abc import Sequence
from typing import Any, Protocol

import anthropic

from tribunal.config import Settings


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


def complete_json(
    llm: LLMClient, system: str, user: str, *, max_tokens: int | None = None
) -> Any:
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


class ScriptedLLM:
    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = deque(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, max_tokens: int | None = None) -> str:
        self.calls.append((system, user))
        if not self._responses:
            raise LLMError("scripted LLM has no responses left")
        return self._responses.popleft()
