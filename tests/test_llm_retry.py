import json

import pytest

from tribunal.llm import LLMError, ScriptedLLM, complete_json, complete_parsed


def test_complete_json_repairs_once() -> None:
    llm = ScriptedLLM(["oops", json.dumps({"a": 1})])
    assert complete_json(llm, "s", "u") == {"a": 1}
    assert len(llm.calls) == 2
    assert llm.calls[1][1].startswith("u")
    assert "not valid JSON" in llm.calls[1][1]


def test_complete_json_gives_up_after_the_retry() -> None:
    with pytest.raises(LLMError):
        complete_json(ScriptedLLM(["a", "b"]), "s", "u")
    with pytest.raises(LLMError):
        complete_json(ScriptedLLM(["a", json.dumps({"a": 1})]), "s", "u", retries=0)


def test_complete_parsed_retries_on_rejection() -> None:
    def parse(data: dict) -> int:
        if data["n"] == 0:
            raise LLMError("bad")
        return data["n"]

    llm = ScriptedLLM([json.dumps({"n": 0}), json.dumps({"n": 1})])
    assert complete_parsed(llm, "s", "u", parse) == 1
    assert "rejected (bad)" in llm.calls[1][1]
