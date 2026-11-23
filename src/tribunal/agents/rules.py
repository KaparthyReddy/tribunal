from tribunal.agents.base import CRITICAL_KINDS, AgentResult
from tribunal.models import Claim, ClaimStatus, Finding, Severity

SURVIVOR_PREFIX = "Surviving mutant at"
UNCOVERED_PREFIX = "No test reaches changed code:"
UNCOVERED_SUFFIX = "have no test coverage"


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


def demote_uncovered(findings: list[Finding]) -> list[Finding]:
    demoted: list[Finding] = []
    for finding in findings:
        uncovered = finding.title.startswith(UNCOVERED_PREFIX) or finding.title.endswith(
            UNCOVERED_SUFFIX
        )
        if finding.source == "blast_radius" and uncovered:
            demoted.append(
                finding.model_copy(
                    update={
                        "severity": Severity.INFO,
                        "title": f"Test gap, syntax unchanged: {finding.title[0].lower()}{finding.title[1:]}",
                        "detail": (
                            "The syntax trees of every changed file are identical, so the change "
                            "cannot behave differently. The missing test coverage was already there."
                        ),
                    }
                )
            )
        else:
            demoted.append(finding)
    return demoted
