import json
from pathlib import Path

from tribunal.agents import AgentResult, AuditContext, Characterizer, Evidence, demote_uncovered
from tribunal.llm import ScriptedLLM
from tribunal.models import Claim, ClaimKind, ClaimStatus, Finding, Severity, Submission, Verdict

NO_CHANGE = Claim(id="c1", text="no change", kind=ClaimKind.NO_BEHAVIOR_CHANGE)


def _ctx(tmp_path: Path) -> AuditContext:
    base, head = tmp_path / "base", tmp_path / "head"
    for root in (base, head):
        root.mkdir()
    submission = Submission(
        repo="o/r", repo_path=str(tmp_path), base_sha="a" * 40, head_sha="b" * 40, title="t"
    )
    return AuditContext(
        submission=submission, base_dir=base, head_dir=head, evidence=Evidence(), diff="diff"
    )


def test_untested_code_findings_are_demoted_only_for_blast_radius() -> None:
    findings = [
        Finding(
            source="blast_radius",
            title="No test reaches changed code: f (a.py)",
            severity=Severity.HIGH,
            command_indexes=[2],
        ),
        Finding(
            source="blast_radius",
            title="3 more changed function(s) have no test coverage",
            severity=Severity.MEDIUM,
        ),
        Finding(
            source="blast_radius",
            title="Wide blast radius: 30 dependent function(s)",
            severity=Severity.LOW,
        ),
        Finding(
            source="skeptic", title="No test reaches changed code: x", severity=Severity.MEDIUM
        ),
    ]
    demoted = demote_uncovered(findings)

    assert [f.severity for f in demoted] == [
        Severity.INFO,
        Severity.INFO,
        Severity.LOW,
        Severity.MEDIUM,
    ]
    assert demoted[0].title == "Test gap, syntax unchanged: no test reaches changed code: f (a.py)"
    assert demoted[1].title == (
        "Test gap, syntax unchanged: 3 more changed function(s) have no test coverage"
    )
    assert demoted[0].command_indexes == [2]
    assert demoted[2:] == findings[2:]
    assert AgentResult().proven_identical is False


def test_a_docs_only_change_is_proven_identical(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (0, "", ""))
    result = Characterizer(ScriptedLLM([]), runner).run(
        _ctx(tmp_path), [NO_CHANGE], {}, ["README.md"]
    )
    assert result.proven_identical
    assert result.behavior_identical
    assert [r.status for r in result.claim_results] == [ClaimStatus.SUPPORTED]


def test_a_changed_data_file_is_not_proven_identical(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (0, "", ""))
    result = Characterizer(ScriptedLLM([]), runner).run(
        _ctx(tmp_path), [NO_CHANGE], {}, ["words.txt"]
    )
    assert not result.proven_identical
    assert not result.behavior_identical
    assert result.claim_results == []


def test_a_formatting_only_change_passes_without_tests(
    make_repo, make_runner, make_pipeline, probes_json
) -> None:
    repo, shas = make_repo(
        [{"lib.py": "def f(a):\n    return a+1\n"}, {"lib.py": "def f(a):\n    return a + 1\n"}]
    )
    llm = ScriptedLLM([json.dumps({"claims": []}), probes_json])
    pipe = make_pipeline(make_runner(lambda workdir, argv: (0, "ok", "")), llm)
    submission = pipe.submit(
        repo_path=str(repo),
        base=shas[0],
        head=shas[1],
        title="Reformat f",
        description="Formatting only.",
    )
    receipt = pipe.run(submission.id)

    by_title = {finding.title: finding for finding in receipt.body.findings}
    assert "Static check: no runtime change" in by_title
    gap = by_title["Test gap, syntax unchanged: no test reaches changed code: f (lib.py)"]
    assert gap.severity is Severity.INFO
    assert receipt.body.verdict is Verdict.PASS


def test_sampled_equality_does_not_hide_missing_tests(
    make_repo, make_runner, make_pipeline, probes_json
) -> None:
    repo, shas = make_repo(
        [
            {"lib.py": "def f(a):\n    return a + 1\n"},
            {"lib.py": "def f(a):\n    return a + 1 + 0\n"},
        ]
    )

    def handler(workdir: Path, argv: list[str]) -> tuple[int, str, str]:
        if argv[-1].endswith("driver"):
            lines = [
                json.dumps({"i": 0, "ok": True, "value": "2", "state": "[[1], {}]"}),
                json.dumps({"trace": {"lib.py": [2]}}),
            ]
            return 0, "\n".join(lines), ""
        return 0, "ok", ""

    call = {"module": "lib", "function": "f", "args": [1], "kwargs": {}, "claim": None}
    llm = ScriptedLLM([json.dumps({"claims": []}), probes_json, json.dumps({"calls": [call]})])
    pipe = make_pipeline(make_runner(handler), llm)
    submission = pipe.submit(
        repo_path=str(repo),
        base=shas[0],
        head=shas[1],
        title="Simplify f",
        description="Tidy.",
    )
    receipt = pipe.run(submission.id)

    by_title = {finding.title: finding for finding in receipt.body.findings}
    assert by_title["No test reaches changed code: f (lib.py)"].severity is Severity.MEDIUM
    assert "Differential check: 1 input(s) compared, 0 differ" in by_title
    assert receipt.body.verdict is Verdict.INCONCLUSIVE
