import shlex
from dataclasses import dataclass, field
from pathlib import Path

from tribunal.agents.base import AgentResult, CommandRunner, Evidence, is_infra_failure, passed
from tribunal.llm import LLMClient, LLMError, complete_json
from tribunal.models import (
    Claim,
    ClaimKind,
    ClaimResult,
    ClaimStatus,
    Finding,
    Severity,
    Submission,
)

MAX_CHECKS = 3
MAX_ARGV = 40
MAX_ARGV_CHARS = 4000
MAX_DIFF_CHARS = 12000
MAX_FILES = 200
OUTPUT_TAIL_CHARS = 1500

PLAN_SYSTEM = """You verify claims made by a coding agent about a code change. Never trust the claim.
Propose at most 3 shell checks that would confirm or refute it.
Checks run in an offline Linux container with the repository mounted at /work.
Only tools present in the container image are available. There is no network.
Each check is an argv array (no shell unless you invoke ["sh", "-c", "..."] yourself).
run_on is "base" (code before the change), "head" (code after), or "both".
A check that reproduces the claimed bug on base and passes on head is the strongest evidence.
If the claim cannot be checked with executable evidence, return no checks and say why.
Output JSON only, no prose:
{"checks": [{"run_on": "head", "argv": ["..."], "purpose": "..."}], "unverifiable_reason": ""}"""

EVAL_SYSTEM = """You judge whether executed evidence supports a claim made about a code change. Be strict.
- "supported": the evidence directly demonstrates the claim.
- "refuted": the evidence contradicts the claim.
- "unverifiable": the evidence does not settle it.
A passing test suite alone does not prove a specific fix.
Commands that failed to run (missing tools, exit 125-127) are not evidence either way.
Output JSON only, no prose:
{"status": "supported|refuted|unverifiable", "explanation": "...", "evidence": [command indexes]}"""


@dataclass
class AuditContext:
    submission: Submission
    base_dir: Path
    head_dir: Path
    evidence: Evidence
    diff: str = ""
    files: list[str] = field(default_factory=list)


@dataclass
class Check:
    run_on: str
    argv: list[str]
    purpose: str = ""


@dataclass
class Baseline:
    base_idx: int
    head_idx: int
    base_passed: bool
    head_passed: bool
    usable: bool


def _tail(text: str, limit: int) -> str:
    return text if len(text) <= limit else "..." + text[-limit:]


def _parse_plan(data: object) -> tuple[list[Check], str]:
    if not isinstance(data, dict):
        raise LLMError("plan must be a JSON object")
    raw = data.get("checks", [])
    if not isinstance(raw, list):
        raise LLMError("plan checks must be a list")

    checks: list[Check] = []
    for item in raw[:MAX_CHECKS]:
        if not isinstance(item, dict):
            continue
        argv = item.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or len(argv) > MAX_ARGV
            or not all(isinstance(arg, str) for arg in argv)
            or sum(len(arg) for arg in argv) > MAX_ARGV_CHARS
        ):
            continue
        run_on = str(item.get("run_on", "head"))
        if run_on not in {"base", "head", "both"}:
            run_on = "head"
        checks.append(Check(run_on=run_on, argv=argv, purpose=str(item.get("purpose", ""))[:300]))
    return checks, str(data.get("unverifiable_reason", ""))[:500]


class Auditor:
    def __init__(self, llm: LLMClient, runner: CommandRunner) -> None:
        self.llm = llm
        self.runner = runner

    def audit(self, ctx: AuditContext, claims: list[Claim]) -> AgentResult:
        result = AgentResult()
        baseline = self._run_baseline(ctx, result)
        for claim in claims:
            self._audit_claim(ctx, claim, baseline, result)
        return result

    def _run_baseline(self, ctx: AuditContext, result: AgentResult) -> Baseline | None:
        argv = ctx.submission.test_command
        if not argv:
            return None

        base_idx, base_rec = ctx.evidence.run(self.runner, ctx.base_dir, argv)
        head_idx, head_rec = ctx.evidence.run(self.runner, ctx.head_dir, argv)
        usable = not (is_infra_failure(base_rec) or is_infra_failure(head_rec))
        baseline = Baseline(
            base_idx=base_idx,
            head_idx=head_idx,
            base_passed=passed(base_rec),
            head_passed=passed(head_rec),
            usable=usable,
        )

        if not usable:
            result.findings.append(
                Finding(
                    source="auditor",
                    title="Test command could not run",
                    detail=f"`{shlex.join(argv)}` failed to start in the sandbox image.",
                    severity=Severity.LOW,
                    command_indexes=[base_idx, head_idx],
                )
            )
        elif baseline.base_passed and not baseline.head_passed:
            result.findings.append(
                Finding(
                    source="auditor",
                    title="Regression: test command passes on base but fails on head",
                    detail=f"`{shlex.join(argv)}` exits 0 on the base commit and non-zero on head.",
                    severity=Severity.HIGH,
                    command_indexes=[base_idx, head_idx],
                )
            )
        return baseline

    def _baseline_refutation(self, claim: Claim, baseline: Baseline | None) -> str | None:
        if baseline is None or not baseline.usable:
            return None
        if (
            claim.kind is ClaimKind.NO_BEHAVIOR_CHANGE
            and baseline.base_passed
            and not baseline.head_passed
        ):
            return "The test command passes on base but fails on head, so behavior changed."
        if claim.kind is ClaimKind.FIXES and not baseline.head_passed:
            return "The test command fails on head, so the claimed fix is not working."
        return None

    def _audit_claim(
        self,
        ctx: AuditContext,
        claim: Claim,
        baseline: Baseline | None,
        result: AgentResult,
    ) -> None:
        reason = self._baseline_refutation(claim, baseline)
        if reason and baseline is not None:
            self._record(
                result,
                claim,
                ClaimStatus.REFUTED,
                reason,
                [baseline.base_idx, baseline.head_idx],
            )
            return

        try:
            checks, unverifiable_reason = self._plan(ctx, claim)
        except LLMError as exc:
            self._record(result, claim, ClaimStatus.UNVERIFIABLE, f"Planning failed: {exc}", [])
            return

        sides: dict[int, str] = {}
        indexes: list[int] = []
        claim_indexes: list[int] = []

        if baseline is not None and baseline.usable:
            sides[baseline.base_idx] = "base"
            sides[baseline.head_idx] = "head"
            indexes.extend([baseline.base_idx, baseline.head_idx])

        for check in checks:
            run_sides = ("base", "head") if check.run_on == "both" else (check.run_on,)
            for side in run_sides:
                workdir = ctx.base_dir if side == "base" else ctx.head_dir
                idx, _ = ctx.evidence.run(self.runner, workdir, check.argv)
                sides[idx] = side
                indexes.append(idx)
                claim_indexes.append(idx)

        if claim.kind is ClaimKind.FIXES and not claim_indexes:
            explanation = unverifiable_reason or "No check targets the claimed fix."
            self._record(result, claim, ClaimStatus.UNVERIFIABLE, explanation, indexes)
            return

        if not indexes:
            explanation = unverifiable_reason or "No executable evidence was available."
            self._record(result, claim, ClaimStatus.UNVERIFIABLE, explanation, [])
            return

        if all(is_infra_failure(ctx.evidence.commands[i]) for i in indexes):
            self._record(
                result,
                claim,
                ClaimStatus.UNVERIFIABLE,
                "Every check failed to run in the sandbox.",
                indexes,
            )
            return

        try:
            status, explanation, cited = self._evaluate(ctx, claim, indexes, sides)
        except LLMError as exc:
            self._record(
                result, claim, ClaimStatus.UNVERIFIABLE, f"Evaluation failed: {exc}", indexes
            )
            return
        self._record(result, claim, status, explanation, cited or indexes)

    def _plan(self, ctx: AuditContext, claim: Claim) -> tuple[list[Check], str]:
        sub = ctx.submission
        files = "\n".join(ctx.files[:MAX_FILES])
        user = (
            f"Claim ({claim.kind.value}): {claim.text}\n\n"
            f"PR title: {sub.title}\n"
            f"PR description:\n{sub.description}\n\n"
            f"Repository test command: {shlex.join(sub.test_command) or '(none given)'}\n\n"
            f"Files:\n{files}\n\n"
            f"Diff (base..head):\n{ctx.diff[:MAX_DIFF_CHARS]}"
        )
        return _parse_plan(complete_json(self.llm, PLAN_SYSTEM, user))

    def _evaluate(
        self,
        ctx: AuditContext,
        claim: Claim,
        indexes: list[int],
        sides: dict[int, str],
    ) -> tuple[ClaimStatus, str, list[int]]:
        blocks: list[str] = []
        for idx in indexes:
            record = ctx.evidence.commands[idx]
            blocks.append(
                f"[{idx}] ({sides.get(idx, '?')}) $ {shlex.join(record.argv)}\n"
                f"exit={record.exit_code} timed_out={record.timed_out}\n"
                f"stdout:\n{_tail(record.stdout, OUTPUT_TAIL_CHARS)}\n"
                f"stderr:\n{_tail(record.stderr, OUTPUT_TAIL_CHARS)}"
            )
        user = f"Claim ({claim.kind.value}): {claim.text}\n\nEvidence:\n\n" + "\n\n".join(blocks)

        data = complete_json(self.llm, EVAL_SYSTEM, user)
        if not isinstance(data, dict):
            raise LLMError("evaluation must be a JSON object")

        try:
            status = ClaimStatus(str(data.get("status", "")).strip().lower())
        except ValueError:
            status = ClaimStatus.UNVERIFIABLE

        explanation = str(data.get("explanation", ""))[:1000]
        allowed = set(indexes)
        cited_raw = data.get("evidence", [])
        cited = [i for i in cited_raw if isinstance(i, int) and i in allowed] if isinstance(
            cited_raw, list
        ) else []
        return status, explanation, cited

    def _record(
        self,
        result: AgentResult,
        claim: Claim,
        status: ClaimStatus,
        explanation: str,
        indexes: list[int],
    ) -> None:
        result.claim_results.append(
            ClaimResult(
                claim_id=claim.id,
                status=status,
                explanation=explanation,
                command_indexes=indexes,
            )
        )
        if status is ClaimStatus.REFUTED:
            result.findings.append(
                Finding(
                    source="auditor",
                    title=f"Claim refuted: {claim.text}",
                    detail=explanation,
                    severity=Severity.HIGH,
                    command_indexes=indexes,
                )
            )
        elif status is ClaimStatus.UNVERIFIABLE:
            result.findings.append(
                Finding(
                    source="auditor",
                    title=f"Claim not verified: {claim.text}",
                    detail=explanation,
                    severity=Severity.LOW,
                    command_indexes=indexes,
                )
            )
