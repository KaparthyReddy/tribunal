from tribunal.agents.base import CRITICAL_KINDS, AgentResult
from tribunal.models import Claim, ClaimStatus, Finding, Severity

SURVIVOR_PREFIX = "Surviving mutant at"


def enforce_fixed_rules(audit: AgentResult, claims: list[Claim]) -> None:
    by_id = {claim.id: claim for claim in claims}
    titles = {finding.title for finding in audit.findings}
    for index, result in enumerate(audit.claim_results):
        claim = by_id.get(result.claim_id)
        if claim is None or claim.kind not in CRITICAL_KINDS:
            continue
        if result.status is not ClaimStatus.SUPPORTED:
            continue
        note = "A model's judgment cannot support this kind of claim; it needs a fixed rule."
        explanation = f"{note} {result.explanation}".strip()[:1000]
        audit.claim_results[index] = result.model_copy(
            update={"status": ClaimStatus.UNVERIFIABLE, "explanation": explanation}
        )
        title = f"Claim not verified: {claim.text}"
        if title not in titles:
            titles.add(title)
            audit.findings.append(
                Finding(
                    source="auditor",
                    title=title,
                    detail=explanation,
                    severity=Severity.LOW,
                    command_indexes=result.command_indexes,
                )
            )


def demote_test_gaps(findings: list[Finding]) -> list[Finding]:
    demoted: list[Finding] = []
    for finding in findings:
        if finding.source == "skeptic" and finding.title.startswith(SURVIVOR_PREFIX):
            demoted.append(
                finding.model_copy(
                    update={
                        "severity": Severity.INFO,
                        "title": f"Test gap, behavior unchanged: {finding.title[0].lower()}{finding.title[1:]}",
                        "detail": (
                            "Behavior was identical on every compared input and the changed code ran, "
                            "so this is a gap in the tests, not an error in the change."
                        ),
                    }
                )
            )
        else:
            demoted.append(finding)
    return demoted
