from tribunal.agents import AgentResult, demote_test_gaps, enforce_fixed_rules
from tribunal.models import Claim, ClaimKind, ClaimResult, ClaimStatus, Finding, Severity

CLAIMS = [
    Claim(id="c1", text="fixes it", kind=ClaimKind.FIXES),
    Claim(id="c2", text="nicer", kind=ClaimKind.OTHER),
    Claim(id="c3", text="no change", kind=ClaimKind.NO_BEHAVIOR_CHANGE),
    Claim(id="c4", text="also no change", kind=ClaimKind.NO_BEHAVIOR_CHANGE),
]


def _audit() -> AgentResult:
    return AgentResult(
        claim_results=[
            ClaimResult(claim_id="c1", status=ClaimStatus.SUPPORTED, command_indexes=[0]),
            ClaimResult(claim_id="c2", status=ClaimStatus.SUPPORTED),
            ClaimResult(claim_id="c3", status=ClaimStatus.SUPPORTED),
            ClaimResult(claim_id="c4", status=ClaimStatus.REFUTED),
        ]
    )


def test_a_model_cannot_support_a_critical_claim() -> None:
    audit = _audit()
    enforce_fixed_rules(audit, CLAIMS)

    statuses = {result.claim_id: result.status for result in audit.claim_results}
    assert statuses == {
        "c1": ClaimStatus.UNVERIFIABLE,
        "c2": ClaimStatus.SUPPORTED,
        "c3": ClaimStatus.UNVERIFIABLE,
        "c4": ClaimStatus.REFUTED,
    }
    assert audit.claim_results[0].command_indexes == [0]
    assert audit.claim_results[0].explanation.startswith("A model's judgment cannot support")
    assert [(f.severity, f.title) for f in audit.findings] == [
        (Severity.LOW, "Claim not verified: fixes it"),
        (Severity.LOW, "Claim not verified: no change"),
    ]


def test_enforcement_is_idempotent_and_does_not_duplicate_findings() -> None:
    audit = _audit()
    audit.findings.append(
        Finding(source="auditor", title="Claim not verified: fixes it", severity=Severity.LOW)
    )
    enforce_fixed_rules(audit, CLAIMS)
    enforce_fixed_rules(audit, CLAIMS)
    assert [f.title for f in audit.findings].count("Claim not verified: fixes it") == 1
    assert len(audit.findings) == 2


def test_surviving_mutants_become_test_gaps() -> None:
    findings = [
        Finding(
            source="skeptic",
            title="Surviving mutant at a.py:2 (0 -> 1)",
            severity=Severity.MEDIUM,
            command_indexes=[3],
        ),
        Finding(
            source="skeptic", title="Mutation score: 1/2 mutants killed", severity=Severity.INFO
        ),
        Finding(source="auditor", title="Surviving mutant at b.py:1 (x)", severity=Severity.MEDIUM),
    ]
    demoted = demote_test_gaps(findings)

    assert demoted[0].severity is Severity.INFO
    assert demoted[0].title == "Test gap, behavior unchanged: surviving mutant at a.py:2 (0 -> 1)"
    assert demoted[0].command_indexes == [3]
    assert demoted[1] == findings[1]
    assert demoted[2] == findings[2]
