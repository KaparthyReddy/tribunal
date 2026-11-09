import json

import pytest

from tribunal.agents import extract_claims
from tribunal.llm import LLMError, ScriptedLLM
from tribunal.models import ClaimKind, Submission


def _submission(**kwargs: str) -> Submission:
    return Submission(
        repo="o/r", repo_path=".", base_sha="a" * 40, head_sha="b" * 40, **kwargs
    )


def test_extracts_dedupes_and_normalizes_kind() -> None:
    payload = {
        "claims": [
            {"text": "Fixes parser crash", "kind": "fixes"},
            {"text": "No behavior change elsewhere", "kind": "no_behavior_change"},
            {"text": "fixes parser crash", "kind": "fixes"},
            {"text": "Faster", "kind": "bogus"},
            {"text": "", "kind": "fixes"},
            "not a dict",
        ]
    }
    llm = ScriptedLLM([json.dumps(payload)])
    claims = extract_claims(llm, _submission(title="Fix parser", description="details"))
    assert [c.id for c in claims] == ["c1", "c2", "c3"]
    assert [c.kind for c in claims] == [
        ClaimKind.FIXES,
        ClaimKind.NO_BEHAVIOR_CHANGE,
        ClaimKind.OTHER,
    ]


def test_accepts_bare_list() -> None:
    llm = ScriptedLLM([json.dumps([{"text": "Adds tests", "kind": "adds_tests"}])])
    claims = extract_claims(llm, _submission(title="t"))
    assert claims[0].kind is ClaimKind.ADDS_TESTS


def test_empty_text_skips_llm() -> None:
    llm = ScriptedLLM([])
    assert extract_claims(llm, _submission()) == []
    assert llm.calls == []


def test_caps_claim_count() -> None:
    items = [{"text": f"claim {i}", "kind": "other"} for i in range(40)]
    llm = ScriptedLLM([json.dumps({"claims": items})])
    assert len(extract_claims(llm, _submission(title="t"))) == 12


def test_bad_output_raises() -> None:
    with pytest.raises(LLMError):
        extract_claims(ScriptedLLM(["nonsense"]), _submission(title="t"))
    with pytest.raises(LLMError):
        extract_claims(ScriptedLLM([json.dumps({"claims": "x"})]), _submission(title="t"))
