import json

import pytest

from tribunal.agents import deterministic_claims, extract_claims
from tribunal.agents.claims import matches_no_change
from tribunal.llm import LLMError, ScriptedLLM
from tribunal.models import ClaimKind, Submission


def _submission(**kwargs: str) -> Submission:
    return Submission(repo="o/r", repo_path=".", base_sha="a" * 40, head_sha="b" * 40, **kwargs)


def _claims_json(*items: dict) -> str:
    return json.dumps({"claims": list(items)})


@pytest.mark.parametrize(
    "text",
    [
        "No behavior change.",
        "no other behavioral changes",
        "No change in behaviour",
        "This doesn't change behavior",
        "Callers are unaffected",
        "It is backward compatible",
        "backwards-compatible",
        "Existing calls are unchanged",
        "A pure refactor",
        "Keeps the same behavior",
    ],
)
def test_no_change_phrases_match(text: str) -> None:
    assert matches_no_change(text)


@pytest.mark.parametrize(
    "text",
    [
        "Fixes the crash on empty input",
        "Add word_count",
        "Return an immutable result",
        "Tidy the retry module",
    ],
)
def test_other_phrases_do_not_match(text: str) -> None:
    assert not matches_no_change(text)


def test_kind_token_text_is_replaced_by_the_matching_sentence() -> None:
    llm = ScriptedLLM(
        [_claims_json({"text": "no_behavior_change", "kind": "no_behavior_change"})]
    )
    claims = extract_claims(
        llm,
        _submission(title="Tidy the retry module", description="Tidy the retry module. No behavior change."),
    )
    assert [(c.id, c.text, c.kind) for c in claims] == [
        ("c1", "No behavior change.", ClaimKind.NO_BEHAVIOR_CHANGE)
    ]


def test_other_kind_tokens_are_dropped() -> None:
    llm = ScriptedLLM([_claims_json({"text": "adds_tests", "kind": "adds_tests"})])
    assert extract_claims(llm, _submission(title="Add tests")) == []


def test_backstop_adds_a_no_change_claim_the_model_dropped() -> None:
    llm = ScriptedLLM(
        [_claims_json({"text": "Makes the return value immutable", "kind": "other"})]
    )
    claims = extract_claims(
        llm,
        _submission(
            title="Return an immutable result",
            description="Return an immutable result from unique_sorted. Callers are unaffected.",
        ),
    )
    assert [(c.id, c.kind) for c in claims] == [
        ("c1", ClaimKind.OTHER),
        ("c2", ClaimKind.NO_BEHAVIOR_CHANGE),
    ]
    assert claims[1].text == "Callers are unaffected."


def test_a_no_change_statement_is_promoted_to_the_right_kind() -> None:
    llm = ScriptedLLM([_claims_json({"text": "No other behavior change", "kind": "other"})])
    claims = extract_claims(llm, _submission(title="t"))
    assert [c.kind for c in claims] == [ClaimKind.NO_BEHAVIOR_CHANGE]


def test_extraction_repairs_unparseable_output_once() -> None:
    good = _claims_json({"text": "Adds tests for parser", "kind": "adds_tests"})
    llm = ScriptedLLM(["not json", good])
    claims = extract_claims(llm, _submission(title="t"))
    assert [c.kind for c in claims] == [ClaimKind.ADDS_TESTS]
    assert len(llm.calls) == 2
    assert "rejected" in llm.calls[1][1]
    with pytest.raises(LLMError):
        extract_claims(ScriptedLLM(["x", "y"]), _submission(title="t"))


def test_deterministic_claims() -> None:
    claims = deterministic_claims(
        _submission(title="Tidy", description="Tidy it. Callers are unaffected.")
    )
    assert [(c.id, c.text, c.kind) for c in claims] == [
        ("c1", "Callers are unaffected.", ClaimKind.NO_BEHAVIOR_CHANGE)
    ]
    assert deterministic_claims(_submission(title="Fix the parser")) == []
