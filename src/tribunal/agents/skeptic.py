import ast
import shutil
from dataclasses import dataclass

from tribunal.agents.auditor import AuditContext
from tribunal.agents.base import AgentResult, CommandRunner, is_infra_failure, passed
from tribunal.agents.mutants import generate_mutants, spread
from tribunal.graph import is_test_file
from tribunal.llm import LLMClient, LLMError, complete_json
from tribunal.models import CommandRecord, Finding, Severity

PROBE_DIR = "tribunal_probes"
MAX_CODE_CHARS = 8000
MAX_SOURCE_CHARS = 6000
MAX_SOURCE_FILES = 3
MAX_DIFF_CHARS = 12000
MAX_MUTANT_FILE_BYTES = 200_000
MAX_SURVIVOR_FINDINGS = 5
TAIL_CHARS = 1200

PROBE_SYSTEM = """You are a skeptical tester. A coding agent produced the change below. Assume it is wrong.
Write up to {n} standalone Python unittest modules that try to break it.
Rules:
- Use only the standard library (unittest, random, itertools, ...) plus the project's own modules.
- Tests run offline in a container with the repository root as the working directory.
  Import project code with normal imports, for example `from pkg.mod import func`.
- Assert the behavior the PR intends. Never assert the current buggy behavior.
- Target boundaries: empty and None inputs, zero, negatives, very large values, unicode,
  duplicates, ordering, error handling, and anything the diff touches indirectly.
- For pure functions add a seeded fuzz loop using random.Random(1234), at most 500 iterations.
- Never mock the code under test. Never touch the network. Never write outside tempfile.
- Keep each module under 80 lines and each test fast.
Output JSON only, no prose:
{"probes": [{"name": "short description", "code": "full python source"}]}"""


@dataclass(frozen=True)
class Probe:
    name: str
    code: str


def _tail(text: str, limit: int = TAIL_CHARS) -> str:
    return text if len(text) <= limit else "..." + text[-limit:]


def _failure_text(record: CommandRecord) -> str:
    return _tail(record.stderr or record.stdout)


class Skeptic:
    def __init__(
        self,
        llm: LLMClient,
        runner: CommandRunner,
        *,
        max_probes: int = 4,
        max_mutants: int = 8,
        probe_timeout_s: int = 30,
        mutant_timeout_s: int = 60,
    ) -> None:
        self.llm = llm
        self.runner = runner
        self.max_probes = max_probes
        self.max_mutants = max_mutants
        self.probe_timeout_s = probe_timeout_s
        self.mutant_timeout_s = mutant_timeout_s

    def attack(self, ctx: AuditContext, ranges: dict[str, list[tuple[int, int]]]) -> AgentResult:
        result = AgentResult()
        self._run_probes(ctx, sorted(ranges), result)
        self._run_mutants(ctx, ranges, result)
        return result

    def _prompt(self, ctx: AuditContext, changed_files: list[str]) -> str:
        sources: list[str] = []
        for file in changed_files:
            if not file.endswith(".py") or is_test_file(file):
                continue
            try:
                text = (ctx.head_dir / file).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            sources.append(f"--- {file} ---\n{text[:MAX_SOURCE_CHARS]}")
            if len(sources) >= MAX_SOURCE_FILES:
                break
        sub = ctx.submission
        return (
            f"PR title: {sub.title}\n"
            f"PR description:\n{sub.description}\n\n"
            f"Diff (base..head):\n{ctx.diff[:MAX_DIFF_CHARS]}\n\n"
            f"Changed files after the change:\n\n" + "\n\n".join(sources)
        )

    def _generate(self, ctx: AuditContext, changed_files: list[str]) -> list[Probe]:
        system = PROBE_SYSTEM.replace("{n}", str(self.max_probes))
        data = complete_json(self.llm, system, self._prompt(ctx, changed_files))
        items = data.get("probes") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise LLMError("probes must be a list")

        probes: list[Probe] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            code = item.get("code")
            if not isinstance(code, str) or not code.strip() or len(code) > MAX_CODE_CHARS:
                continue
            try:
                ast.parse(code)
            except (SyntaxError, ValueError):
                continue
            name = str(item.get("name", "probe")).strip()[:80] or "probe"
            probes.append(Probe(name=name, code=code))
            if len(probes) >= self.max_probes:
                break
        return probes

    def _write(self, ctx: AuditContext, probes: list[Probe]) -> None:
        for root in (ctx.base_dir, ctx.head_dir):
            directory = root / PROBE_DIR
            directory.mkdir(exist_ok=True)
            (directory / "__init__.py").write_text("", encoding="utf-8")
            for number, probe in enumerate(probes, start=1):
                (directory / f"probe_{number}.py").write_text(probe.code, encoding="utf-8")

    def _cleanup(self, ctx: AuditContext) -> None:
        for root in (ctx.base_dir, ctx.head_dir):
            shutil.rmtree(root / PROBE_DIR, ignore_errors=True)

    def _run_probes(self, ctx: AuditContext, changed_files: list[str], result: AgentResult) -> None:
        try:
            probes = self._generate(ctx, changed_files)
        except LLMError as exc:
            result.findings.append(
                Finding(
                    source="skeptic",
                    title="Probe generation failed",
                    detail=str(exc)[:500],
                    severity=Severity.LOW,
                )
            )
            return
        if not probes:
            result.findings.append(
                Finding(
                    source="skeptic",
                    title="Skeptic produced no valid probes",
                    severity=Severity.LOW,
                )
            )
            return

        self._write(ctx, probes)
        try:
            for number, probe in enumerate(probes, start=1):
                self._run_probe(ctx, number, probe, result)
        finally:
            self._cleanup(ctx)

    def _run_probe(self, ctx: AuditContext, number: int, probe: Probe, result: AgentResult) -> None:
        argv = ["python", "-m", "unittest", f"{PROBE_DIR}.probe_{number}"]
        head_idx, head = ctx.evidence.run(
            self.runner, ctx.head_dir, argv, timeout_s=self.probe_timeout_s
        )
        if passed(head):
            return
        if is_infra_failure(head):
            result.findings.append(
                Finding(
                    source="skeptic",
                    title=f"Probe could not run: {probe.name}",
                    detail=_failure_text(head),
                    severity=Severity.LOW,
                    command_indexes=[head_idx],
                )
            )
            return

        base_idx, base = ctx.evidence.run(
            self.runner, ctx.base_dir, argv, timeout_s=self.probe_timeout_s
        )
        indexes = [head_idx, base_idx]
        state = "hangs" if head.timed_out else "fails"

        if passed(base):
            result.findings.append(
                Finding(
                    source="skeptic",
                    title=f"Probe broke the change: {probe.name}",
                    detail=f"Passes on base, {state} on head.\n{_failure_text(head)}",
                    severity=Severity.HIGH,
                    command_indexes=indexes,
                )
            )
        elif is_infra_failure(base):
            result.findings.append(
                Finding(
                    source="skeptic",
                    title=f"Probe {state} on head and base run was unavailable: {probe.name}",
                    detail=_failure_text(head),
                    severity=Severity.LOW,
                    command_indexes=indexes,
                )
            )
        else:
            result.findings.append(
                Finding(
                    source="skeptic",
                    title=f"Probe fails on both base and head: {probe.name}",
                    detail=_failure_text(head),
                    severity=Severity.LOW,
                    command_indexes=indexes,
                )
            )

    def _run_mutants(
        self,
        ctx: AuditContext,
        ranges: dict[str, list[tuple[int, int]]],
        result: AgentResult,
    ) -> None:
        argv = ctx.submission.test_command
        if not argv:
            result.findings.append(
                Finding(
                    source="skeptic",
                    title="Mutation testing skipped: no test command provided",
                    severity=Severity.INFO,
                )
            )
            return

        pool = []
        for file in sorted(ranges):
            if not file.endswith(".py") or is_test_file(file):
                continue
            path = ctx.head_dir / file
            try:
                if path.stat().st_size > MAX_MUTANT_FILE_BYTES:
                    continue
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            pool.extend(generate_mutants(source, file, ranges[file], self.max_mutants))
        mutants = spread(pool, self.max_mutants)
        if not mutants:
            return

        base_idx, baseline = ctx.evidence.run(
            self.runner, ctx.head_dir, argv, timeout_s=self.mutant_timeout_s
        )
        if not passed(baseline):
            result.findings.append(
                Finding(
                    source="skeptic",
                    title="Mutation testing skipped: test command does not pass on head",
                    severity=Severity.LOW,
                    command_indexes=[base_idx],
                )
            )
            return

        killed = 0
        survivors = []
        for mutant in mutants:
            path = ctx.head_dir / mutant.file
            original = path.read_bytes()
            try:
                path.write_text(mutant.source, encoding="utf-8")
                idx, record = ctx.evidence.run(
                    self.runner, ctx.head_dir, argv, timeout_s=self.mutant_timeout_s
                )
            finally:
                path.write_bytes(original)
            if is_infra_failure(record):
                continue
            if passed(record):
                survivors.append((mutant, idx))
            else:
                killed += 1

        for mutant, idx in survivors[:MAX_SURVIVOR_FINDINGS]:
            result.findings.append(
                Finding(
                    source="skeptic",
                    title=f"Surviving mutant at {mutant.file}:{mutant.line} ({mutant.description})",
                    detail="The test command still passes after this mutation, so tests do not detect it.",
                    severity=Severity.MEDIUM,
                    command_indexes=[idx],
                )
            )
        total = killed + len(survivors)
        if total:
            result.findings.append(
                Finding(
                    source="skeptic",
                    title=f"Mutation score: {killed}/{total} mutants killed",
                    severity=Severity.INFO,
                )
            )
