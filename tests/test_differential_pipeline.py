import json
from pathlib import Path

from tribunal.llm import ScriptedLLM
from tribunal.models import ClaimStatus, Verdict


def test_false_no_change_claim_fails_the_pipeline(
    scenario, make_runner, make_pipeline, probes_json, is_head
) -> None:
    repo, shas = scenario

    def handler(workdir: Path, argv: list[str]) -> tuple[int, str, str]:
        if argv[-1].endswith("driver"):
            value = "3" if is_head(workdir) else "2"
            return 0, json.dumps({"i": 0, "ok": True, "value": value}), ""
        return 0, "ok", ""

    llm = ScriptedLLM(
        [
            json.dumps({"claims": [{"text": "no behavior change", "kind": "no_behavior_change"}]}),
            json.dumps({"checks": []}),
            json.dumps(
                {
                    "calls": [
                        {"module": "lib", "function": "f", "args": [1], "kwargs": {}, "claim": None}
                    ]
                }
            ),
            probes_json,
        ]
    )
    pipe = make_pipeline(make_runner(handler), llm)
    submission = pipe.submit(
        repo_path=str(repo),
        base=shas[0],
        head=shas[1],
        title="Refactor f",
        description="No behavior change.",
    )
    receipt = pipe.run(submission.id)

    assert len(llm.calls) == 4
    assert receipt.body.verdict is Verdict.FAIL
    assert [r.status for r in receipt.body.claim_results] == [ClaimStatus.REFUTED]
    titles = [finding.title for finding in receipt.body.findings]
    assert "Claim refuted: no behavior change" in titles
    assert not any(title.startswith("Claim not verified") for title in titles)


def test_differential_can_be_disabled(
    scenario, make_runner, make_pipeline, probes_json
) -> None:
    repo, shas = scenario
    llm = ScriptedLLM(
        [
            json.dumps({"claims": [{"text": "no behavior change", "kind": "no_behavior_change"}]}),
            json.dumps({"checks": []}),
            probes_json,
        ]
    )
    pipe = make_pipeline(
        make_runner(lambda workdir, argv: (0, "ok", "")), llm, differential=False
    )
    submission = pipe.submit(
        repo_path=str(repo),
        base=shas[0],
        head=shas[1],
        title="Refactor f",
        description="No behavior change.",
    )
    receipt = pipe.run(submission.id)

    assert len(llm.calls) == 3
    assert receipt.body.verdict is Verdict.INCONCLUSIVE
