from dataclasses import dataclass

from tribunal.agents.base import is_infra_failure
from tribunal.models import (
    Claim,
    ClaimKind,
    ClaimResult,
    ClaimStatus,
    CommandRecord,
    Finding,
    ReceiptBody,
    Severity,
    SignedReceipt,
    Submission,
    Verdict,
)
from tribunal.receipts import ReceiptSigner

SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}
CRITICAL_KINDS = frozenset({ClaimKind.FIXES, ClaimKind.NO_BEHAVIOR_CHANGE})


@dataclass(frozen=True)
class JudgePolicy:
    fail_at: Severity = Severity.HIGH
    review_at: Severity = Severity.MEDIUM
    max_reasons: int = 8


class Judge:
    def __init__(self, signer: ReceiptSigner, policy: JudgePolicy | None = None) -> None:
        self.signer = signer
        self.policy = policy or JudgePolicy()

    def decide(
        self,
        submission: Submission,
        claims: list[Claim],
        claim_results: list[ClaimResult],
        findings: list[Finding],
        commands: list[CommandRecord],
    ) -> tuple[Verdict, str]:
        fail_rank = SEVERITY_RANK[self.policy.fail_at]
        review_rank = SEVERITY_RANK[self.policy.review_at]
        fail: dict[str, None] = {}
        review: dict[str, None] = {}
        results = {r.claim_id: r for r in claim_results}

        for finding in findings:
            rank = SEVERITY_RANK[finding.severity]
            if rank >= fail_rank:
                fail[finding.title] = None
            elif rank >= review_rank:
                review[finding.title] = None

        for claim in claims:
            outcome = results.get(claim.id)
            if outcome is not None and outcome.status is ClaimStatus.REFUTED:
                fail[f"Claim refuted: {claim.text}"] = None
            elif (
                outcome is None or outcome.status is ClaimStatus.UNVERIFIABLE
            ) and claim.kind in CRITICAL_KINDS:
                review[f"Critical claim not verified: {claim.text}"] = None

        if not commands:
            review["No executable evidence was produced"] = None
        elif all(is_infra_failure(c) for c in commands):
            review["Every sandboxed command failed to run"] = None

        if fail:
            rationale = self._rationale("blocking issue(s)", list(fail))
            if review:
                rationale += f" {len(review)} additional item(s) need review."
            return Verdict.FAIL, rationale
        if review:
            return Verdict.INCONCLUSIVE, self._rationale("item(s) need human review", list(review))

        supported = sum(1 for r in claim_results if r.status is ClaimStatus.SUPPORTED)
        return Verdict.PASS, (
            f"No blocking issues at {submission.head_sha[:12]}. "
            f"{len(commands)} sandboxed command(s) run, "
            f"{supported} of {len(claims)} claim(s) supported."
        )

    def _rationale(self, label: str, reasons: list[str]) -> str:
        shown = reasons[: self.policy.max_reasons]
        lines = [f"{len(reasons)} {label}:"]
        lines.extend(f"- {reason}" for reason in shown)
        if len(reasons) > len(shown):
            lines.append(f"- ...and {len(reasons) - len(shown)} more")
        return "\n".join(lines)

    def issue(
        self,
        submission: Submission,
        claims: list[Claim],
        claim_results: list[ClaimResult],
        findings: list[Finding],
        commands: list[CommandRecord],
    ) -> SignedReceipt:
        verdict, rationale = self.decide(submission, claims, claim_results, findings, commands)
        ordered = sorted(findings, key=lambda f: SEVERITY_RANK[f.severity], reverse=True)
        body = ReceiptBody(
            submission_id=submission.id,
            repo=submission.repo,
            base_sha=submission.base_sha,
            head_sha=submission.head_sha,
            verdict=verdict,
            rationale=rationale,
            claims=claims,
            claim_results=claim_results,
            findings=ordered,
            commands=commands,
        )
        return self.signer.sign(body)
