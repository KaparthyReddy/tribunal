import json
from pathlib import Path

from tribunal.agents import AuditContext, Auditor, Evidence
from tribunal.llm import ScriptedLLM
from tribunal.models import Claim, ClaimKind, ClaimStatus, Severity, Submission


def _ctx(tmp_path: Path, test_command: list[str] | None = None) -> AuditContext:
    base = tmp_path / "base"
    head = tmp_path / "head"
    base.mkdir()
    head.mkdir()
    submission = Submission(
        repo="o/r",
        repo_path=str(tmp_path),
        base_sha="a" * 40,
        head_sha="b" * 40,
        title="t",
        test_command=test_command or [],
    )
    return AuditContext(submission=submission, base_dir=base, head_dir=head, evidence=Evidence())


def _plan(*checks: dict) -> str:
    return json.dumps({"checks": list(checks)})


def _check(argv: list[str], run_on: str = "head") -> dict:
    return {"run_on": run_on, "argv": argv, "purpose": "p"}


def _verdict(status: str, evidence: list[int] | None = None) -> str:
    return json.dumps({"status": status, "explanation": "e", "evidence": evidence or []})


def _claim(kind: ClaimKind) -> Claim:
    return Claim(id="c1", text="the claim", kind=kind)


def test_regression_refutes_without_llm(tmp_path: Path, make_runner) -> None:
    runner = make_runner(
        lambda workdir, argv: (0, "", "") if workdir.name == "base" else (1, "FAILED", "")
    )
    llm = ScriptedLLM([])
    ctx = _ctx(tmp_path, ["pytest"])
    result = Auditor(llm, runner).audit(ctx, [_claim(ClaimKind.NO_BEHAVIOR_CHANGE)])

    assert result.claim_results[0].status is ClaimStatus.REFUTED
    assert result.claim_results[0].command_indexes == [0, 1]
    assert llm.calls == []
    assert len(ctx.evidence.commands) == 2
    assert any(f.severity is Severity.HIGH and "Regression" in f.title for f in result.findings)


def test_fix_with_failing_head_refuted(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (1, "FAILED", ""))
    llm = ScriptedLLM([])
    result = Auditor(llm, runner).audit(_ctx(tmp_path, ["pytest"]), [_claim(ClaimKind.FIXES)])
    assert result.claim_results[0].status is ClaimStatus.REFUTED
    assert llm.calls == []


def test_fix_supported_with_targeted_check(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (0, "1\n", ""))
    llm = ScriptedLLM([_plan(_check(["python", "-c", "print(1)"])), _verdict("supported", [0])])
    ctx = _ctx(tmp_path)
    result = Auditor(llm, runner).audit(ctx, [_claim(ClaimKind.FIXES)])

    assert result.claim_results[0].status is ClaimStatus.SUPPORTED
    assert result.claim_results[0].command_indexes == [0]
    assert result.findings == []
    assert len(ctx.evidence.commands) == 1


def test_fix_without_checks_is_unverifiable(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (0, "", ""))
    llm = ScriptedLLM([_plan()])
    result = Auditor(llm, runner).audit(_ctx(tmp_path), [_claim(ClaimKind.FIXES)])

    assert result.claim_results[0].status is ClaimStatus.UNVERIFIABLE
    assert len(llm.calls) == 1
    assert runner.calls == []


def test_infra_failure_is_unverifiable(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (127, "", "not found"))
    llm = ScriptedLLM([_plan(_check(["missing-tool"]))])
    result = Auditor(llm, runner).audit(_ctx(tmp_path), [_claim(ClaimKind.OTHER)])

    assert result.claim_results[0].status is ClaimStatus.UNVERIFIABLE
    assert len(llm.calls) == 1


def test_llm_refutation_creates_finding(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (1, "boom", ""))
    llm = ScriptedLLM([_plan(_check(["python", "-c", "1/0"])), _verdict("refuted", [0])])
    result = Auditor(llm, runner).audit(_ctx(tmp_path), [_claim(ClaimKind.OTHER)])

    assert result.claim_results[0].status is ClaimStatus.REFUTED
    assert any(f.severity is Severity.HIGH and "refuted" in f.title for f in result.findings)


def test_planning_failure_is_unverifiable(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (0, "", ""))
    llm = ScriptedLLM(["not json"])
    result = Auditor(llm, runner).audit(_ctx(tmp_path), [_claim(ClaimKind.OTHER)])
    assert result.claim_results[0].status is ClaimStatus.UNVERIFIABLE


def test_cited_indexes_are_filtered(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (0, "ok", ""))
    llm = ScriptedLLM([_plan(_check(["true"])), _verdict("supported", [0, 99])])
    result = Auditor(llm, runner).audit(_ctx(tmp_path), [_claim(ClaimKind.OTHER)])
    assert result.claim_results[0].command_indexes == [0]


def test_invalid_checks_are_dropped(tmp_path: Path, make_runner) -> None:
    runner = make_runner(lambda workdir, argv: (0, "", ""))
    bad = {"run_on": "head", "argv": "echo hi"}
    llm = ScriptedLLM([_plan(bad, _check([]))])
    result = Auditor(llm, runner).audit(_ctx(tmp_path), [_claim(ClaimKind.FIXES)])
    assert result.claim_results[0].status is ClaimStatus.UNVERIFIABLE
    assert runner.calls == []
