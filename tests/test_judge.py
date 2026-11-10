from datetime import UTC, datetime
from pathlib import Path

import pytest

from tribunal.agents import Judge, JudgePolicy
from tribunal.models import (
    Claim,
    ClaimKind,
    ClaimResult,
    ClaimStatus,
    CommandRecord,
    Finding,
    Severity,
    Submission,
    Verdict,
)
from tribunal.receipts import ReceiptSigner, verify_receipt


@pytest.fixture
def judge(tmp_path: Path) -> Judge:
    return Judge(ReceiptSigner.load_or_create(tmp_path / "key.pem"))


@pytest.fixture
def submission() -> Submission:
    return Submission(repo="o/r", repo_path=".", base_sha="a" * 40, head_sha="b" * 40)


def _command(exit_code: int | None = 0) -> CommandRecord:
    return CommandRecord(
        argv=["x"],
        image="img",
        exit_code=exit_code,
        duration_s=0.1,
        started_at=datetime.now(UTC),
    )


def _finding(severity: Severity, title: str = "finding") -> Finding:
    return Finding(source="s", title=title, severity=severity)


def _result(claim_id: str, status: ClaimStatus) -> ClaimResult:
    return ClaimResult(claim_id=claim_id, status=status)


def test_pass(judge: Judge, submission: Submission) -> None:
    claims = [Claim(id="c1", text="fixes it", kind=ClaimKind.FIXES)]
    verdict, rationale = judge.decide(
        submission,
        claims,
        [_result("c1", ClaimStatus.SUPPORTED)],
        [_finding(Severity.LOW), _finding(Severity.INFO)],
        [_command()],
    )
    assert verdict is Verdict.PASS
    assert "1 of 1" in rationale


def test_high_finding_fails(judge: Judge, submission: Submission) -> None:
    verdict, rationale = judge.decide(
        submission, [], [], [_finding(Severity.HIGH, "boom")], [_command()]
    )
    assert verdict is Verdict.FAIL
    assert "boom" in rationale


def test_refuted_claim_fails_without_finding(judge: Judge, submission: Submission) -> None:
    claims = [Claim(id="c1", text="no change", kind=ClaimKind.NO_BEHAVIOR_CHANGE)]
    verdict, rationale = judge.decide(
        submission, claims, [_result("c1", ClaimStatus.REFUTED)], [], [_command()]
    )
    assert verdict is Verdict.FAIL
    assert "Claim refuted: no change" in rationale


def test_refuted_claim_and_finding_are_deduplicated(judge: Judge, submission: Submission) -> None:
    claims = [Claim(id="c1", text="x", kind=ClaimKind.OTHER)]
    finding = _finding(Severity.HIGH, "Claim refuted: x")
    verdict, rationale = judge.decide(
        submission, claims, [_result("c1", ClaimStatus.REFUTED)], [finding], [_command()]
    )
    assert verdict is Verdict.FAIL
    assert rationale.startswith("1 blocking")


def test_no_commands_is_inconclusive(judge: Judge, submission: Submission) -> None:
    verdict, rationale = judge.decide(submission, [], [], [], [])
    assert verdict is Verdict.INCONCLUSIVE
    assert "No executable evidence" in rationale


def test_unverified_critical_claim_is_inconclusive(judge: Judge, submission: Submission) -> None:
    claims = [Claim(id="c1", text="fixes it", kind=ClaimKind.FIXES)]
    verdict, _ = judge.decide(
        submission, claims, [_result("c1", ClaimStatus.UNVERIFIABLE)], [], [_command()]
    )
    assert verdict is Verdict.INCONCLUSIVE


def test_missing_result_for_critical_claim_is_inconclusive(
    judge: Judge, submission: Submission
) -> None:
    claims = [Claim(id="c1", text="fixes it", kind=ClaimKind.FIXES)]
    verdict, _ = judge.decide(submission, claims, [], [], [_command()])
    assert verdict is Verdict.INCONCLUSIVE


def test_unverified_minor_claim_still_passes(judge: Judge, submission: Submission) -> None:
    claims = [Claim(id="c1", text="nicer", kind=ClaimKind.OTHER)]
    verdict, _ = judge.decide(
        submission, claims, [_result("c1", ClaimStatus.UNVERIFIABLE)], [], [_command()]
    )
    assert verdict is Verdict.PASS


def test_medium_finding_is_inconclusive(judge: Judge, submission: Submission) -> None:
    verdict, _ = judge.decide(submission, [], [], [_finding(Severity.MEDIUM)], [_command()])
    assert verdict is Verdict.INCONCLUSIVE


def test_all_infra_failures_inconclusive(judge: Judge, submission: Submission) -> None:
    verdict, rationale = judge.decide(submission, [], [], [], [_command(127), _command(125)])
    assert verdict is Verdict.INCONCLUSIVE
    assert "failed to run" in rationale


def test_fail_beats_inconclusive(judge: Judge, submission: Submission) -> None:
    findings = [_finding(Severity.HIGH, "bad"), _finding(Severity.MEDIUM, "meh")]
    verdict, rationale = judge.decide(submission, [], [], findings, [_command()])
    assert verdict is Verdict.FAIL
    assert "1 additional item(s) need review" in rationale


def test_custom_policy(tmp_path: Path, submission: Submission) -> None:
    strict = Judge(
        ReceiptSigner.load_or_create(tmp_path / "key.pem"),
        JudgePolicy(fail_at=Severity.MEDIUM),
    )
    verdict, _ = strict.decide(submission, [], [], [_finding(Severity.MEDIUM)], [_command()])
    assert verdict is Verdict.FAIL


def test_issue_signs_and_sorts_findings(judge: Judge, submission: Submission) -> None:
    findings = [
        _finding(Severity.LOW, "l"),
        _finding(Severity.HIGH, "h"),
        _finding(Severity.INFO, "i"),
    ]
    receipt = judge.issue(submission, [], [], findings, [_command()])
    assert verify_receipt(receipt)
    assert receipt.body.verdict is Verdict.FAIL
    assert [f.title for f in receipt.body.findings] == ["h", "l", "i"]
    assert receipt.body.submission_id == submission.id
    assert receipt.body.head_sha == submission.head_sha
