import json

import pytest

from tribunal.llm import LLMError, ScriptedLLM, complete_json, extract_json


def test_extract_plain_object() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_from_fence() -> None:
    assert extract_json('Here:\n```json\n{"a": [1, 2]}\n```\nDone') == {"a": [1, 2]}


def test_extract_after_prose() -> None:
    assert extract_json('Sure. {"ok": true} hope that helps') == {"ok": True}


def test_extract_array() -> None:
    assert extract_json("[1, 2, 3]") == [1, 2, 3]


def test_extract_failure() -> None:
    with pytest.raises(LLMError):
        extract_json("no json here")


def test_scripted_llm_order_and_exhaustion() -> None:
    llm = ScriptedLLM(["one", json.dumps({"x": 1})])
    assert llm.complete("s", "u") == "one"
    assert complete_json(llm, "s", "u") == {"x": 1}
    assert len(llm.calls) == 2
    with pytest.raises(LLMError):
        llm.complete("s", "u")
