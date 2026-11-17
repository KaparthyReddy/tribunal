import re
from pathlib import Path

from tribunal.agents.auditor import AuditContext
from tribunal.agents.base import AgentResult, CommandRunner, is_infra_failure, passed
from tribunal.graph import is_test_file
from tribunal.models import Claim, ClaimKind, ClaimResult, ClaimStatus, CommandRecord, Finding, Severity

IMPORT_FAILURE = re.compile(r"\b(?:ImportError|ModuleNotFoundError)\b")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


class FailToPass:
    def __init__(self, runner: CommandRunner, *, timeout_s: int = 120) -> None:
        self.runner = runner
        self.timeout_s = timeout_s

    def run(self, ctx: AuditContext, claims: list[Claim], changed_files: list[str]) -> AgentResult:
        result = AgentResult()
        fixes = [claim for claim in claims if claim.kind is ClaimKind.FIXES]
        argv = ctx.submission.test_command
        if not fixes or not argv:
            return result

        tests: dict[str, str] = {}
        for path in changed_files:
            if path.endswith(".py") and is_test_file(path):
                content = _read(ctx.head_dir / path)
                if content is not None:
                    tests[path] = content
        if not tests:
            return result

        prior_base = self._prior(ctx, argv, "base")
        if prior_base is not None and not passed(ctx.evidence.commands[prior_base]):
            return result
        head_index = self._prior(ctx, argv, "head")
        if head_index is None:
            head_index, _ = ctx.evidence.run(
                self.runner, ctx.head_dir, argv, timeout_s=self.timeout_s
            )
        if not passed(ctx.evidence.commands[head_index]):
            return result

        base_index, base = self._run_on_base(ctx, argv, tests)
        if base.timed_out or is_infra_failure(base) or base.exit_code == 0:
            return result

        indexes = [base_index, head_index]
        if IMPORT_FAILURE.search(base.stdout + base.stderr):
            result.findings.append(
                self._finding(
                    "Changed test fails on base because of an import error",
                    "That is not accepted as fail-to-pass evidence.",
                    indexes,
                )
            )
            return result
        if len(fixes) != 1:
            result.findings.append(
                self._finding(
                    "A changed test fails on base and passes on head",
                    "Several fixes are claimed, so it cannot be tied to one of them.",
                    indexes,
                )
            )
            return result

        result.claim_results.append(
            ClaimResult(
                claim_id=fixes[0].id,
                status=ClaimStatus.SUPPORTED,
                explanation=(
                    "A test changed in this diff fails on the base commit and passes on head: "
                    + ", ".join(sorted(tests))
                ),
                command_indexes=indexes,
            )
        )
        return result

    @staticmethod
    def _prior(ctx: AuditContext, argv: list[str], side: str) -> int | None:
        for index, command in enumerate(ctx.evidence.commands):
            if command.argv == argv and command.side == side and not command.overlay:
                return index
        return None

    def _run_on_base(
        self, ctx: AuditContext, argv: list[str], tests: dict[str, str]
    ) -> tuple[int, CommandRecord]:
        saved: dict[str, bytes | None] = {}
        for relative, content in tests.items():
            target = ctx.base_dir / relative
            saved[relative] = target.read_bytes() if target.is_file() else None
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        try:
            return ctx.evidence.run(
                self.runner, ctx.base_dir, argv, timeout_s=self.timeout_s, overlay=tests
            )
        finally:
            for relative, original in saved.items():
                target = ctx.base_dir / relative
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(original)

    @staticmethod
    def _finding(title: str, detail: str, indexes: list[int]) -> Finding:
        return Finding(
            source="fail_to_pass",
            title=title,
            detail=detail,
            severity=Severity.INFO,
            command_indexes=indexes,
        )
