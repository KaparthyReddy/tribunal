import json
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from tribunal.agents.auditor import AuditContext
from tribunal.agents.base import AgentResult, CommandRunner, is_infra_failure
from tribunal.graph import build_callgraph, is_test_file
from tribunal.llm import LLMClient, LLMError, complete_json
from tribunal.models import Claim, ClaimKind, ClaimResult, ClaimStatus, Finding, Severity

CHAR_DIR = "tribunal_chars"
ARGV = ["python", "-m", f"{CHAR_DIR}.driver"]
MAX_CALLS = 24
MAX_FUNCTIONS = 6
MAX_SOURCE_CHARS = 1500
MAX_DIFF_CHARS = 8000
MAX_CALL_CHARS = 2000
IMPORT_ERRORS = frozenset({"ModuleNotFoundError", "ImportError"})

DRIVER = """\
import contextlib
import copy
import importlib
import io
import json
import signal

CALL_TIMEOUT_S = 5


class _Timeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise _Timeout()


def _describe(value):
    text = repr(value)
    return text if len(text) <= 500 else text[:500] + "..."


def main():
    with open("tribunal_chars/calls.json", encoding="utf-8") as handle:
        calls = json.load(handle)
    signal.signal(signal.SIGALRM, _on_alarm)
    for index, call in enumerate(calls):
        signal.alarm(CALL_TIMEOUT_S)
        try:
            module = importlib.import_module(call["module"])
            function = getattr(module, call["function"])
            args = copy.deepcopy(call["args"])
            kwargs = copy.deepcopy(call["kwargs"])
            with contextlib.redirect_stdout(io.StringIO()):
                value = function(*args, **kwargs)
            record = {"i": index, "ok": True, "value": _describe(value)}
        except _Timeout:
            record = {"i": index, "ok": False, "exc": "Timeout", "msg": ""}
        except BaseException as exc:
            record = {"i": index, "ok": False, "exc": type(exc).__name__, "msg": str(exc)[:200]}
        finally:
            signal.alarm(0)
        print(json.dumps(record), flush=True)


main()
"""

SYSTEM = """You design test inputs for comparing two versions of the same Python functions.
A coding agent changed the functions below. Your calls will run on the old and the new version,
and the outputs will be compared, so choose inputs that would expose any difference in behavior.
Rules:
- Only call the listed functions, using the exact module and function names given.
- args is a JSON array and kwargs is a JSON object. Use JSON values only.
- Return at most {n} calls in total.
- Cover typical values, empty inputs, None, zero, negatives, boundaries, duplicates,
  unordered input, mixed case, padded whitespace, punctuation and unicode.
- Include calls that omit optional arguments so default values are exercised.
- For every claim of kind fixes, include the exact input the claim describes and set "claim"
  to that claim's id. Use null for all other calls.
- Never include calls that depend on time, randomness, files or the network.
Output JSON only, no prose:
{"calls": [{"module": "...", "function": "...", "args": [], "kwargs": {}, "claim": null}]}"""


@dataclass(frozen=True)
class Target:
    file: str
    module: str
    function: str
    source: str


@dataclass(frozen=True)
class Call:
    module: str
    function: str
    args: list[Any]
    kwargs: dict[str, Any]
    claim: str | None = None


def module_name(path: str) -> str | None:
    pure = PurePosixPath(path)
    if pure.suffix != ".py":
        return None
    parts = pure.parent.parts if pure.name == "__init__.py" else pure.with_suffix("").parts
    if not parts or not all(part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def select_targets(
    base_dir: Path,
    head_dir: Path,
    ranges: dict[str, list[tuple[int, int]]],
    limit: int = MAX_FUNCTIONS,
) -> list[Target]:
    head_graph = build_callgraph(head_dir)
    base_graph = build_callgraph(base_dir)

    found = {}
    for file, spans in sorted(ranges.items()):
        if not file.endswith(".py") or is_test_file(file):
            continue
        for start, end in spans:
            for symbol in head_graph.symbols_in(file, start, end):
                if symbol.is_module or "." in symbol.qualname:
                    continue
                if symbol.key in base_graph.symbols:
                    found[symbol.key] = symbol

    targets: list[Target] = []
    for symbol in sorted(found.values(), key=lambda s: (s.file, s.start)):
        module = module_name(symbol.file)
        if module is None:
            continue
        try:
            lines = (head_dir / symbol.file).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        source = "\n".join(lines[symbol.start - 1 : symbol.end])[:MAX_SOURCE_CHARS]
        targets.append(Target(symbol.file, module, symbol.name, source))
        if len(targets) >= limit:
            break
    return targets


def parse_calls(
    data: Any, targets: list[Target], claims: list[Claim], limit: int = MAX_CALLS
) -> list[Call]:
    items = data.get("calls") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise LLMError("calls must be a list")

    allowed = {(target.module, target.function) for target in targets}
    claim_ids = {claim.id for claim in claims}
    calls: list[Call] = []
    seen: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            continue
        module = item.get("module")
        function = item.get("function")
        if (module, function) not in allowed:
            continue
        args = item.get("args", [])
        kwargs = item.get("kwargs", {})
        if not isinstance(args, list) or not isinstance(kwargs, dict):
            continue
        if not all(isinstance(key, str) for key in kwargs):
            continue
        claim = item.get("claim")
        claim = claim if isinstance(claim, str) and claim in claim_ids else None
        try:
            key = json.dumps([module, function, args, kwargs], sort_keys=True)
        except (TypeError, ValueError):
            continue
        if len(key) > MAX_CALL_CHARS or key in seen:
            continue
        seen.add(key)
        calls.append(Call(module, function, args, kwargs, claim))
        if len(calls) >= limit:
            break
    return calls


def parse_results(stdout: str) -> dict[int, dict[str, Any]]:
    results: dict[int, dict[str, Any]] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and isinstance(record.get("i"), int):
            results[record["i"]] = record
    return results


def _signature(record: dict[str, Any]) -> tuple[str, str]:
    if record.get("ok"):
        return ("ok", str(record.get("value", "")))
    return ("exc", str(record.get("exc", "?")))


def _label(record: dict[str, Any]) -> str:
    if record.get("ok"):
        return f"returned {record.get('value', '')}"
    return f"raised {record.get('exc', '?')}"


def _call_text(call: Call) -> str:
    parts = [repr(arg) for arg in call.args]
    parts += [f"{key}={value!r}" for key, value in call.kwargs.items()]
    text = f"{call.function}({', '.join(parts)})"
    return text if len(text) <= 120 else text[:117] + "..."


def _prompt(ctx: AuditContext, claims: list[Claim], targets: list[Target]) -> str:
    functions = "\n\n".join(f"# {t.module}.{t.function}\n{t.source}" for t in targets)
    claim_lines = "\n".join(f"{c.id} ({c.kind.value}): {c.text}" for c in claims)
    return (
        f"PR title: {ctx.submission.title}\n\n"
        f"Claims:\n{claim_lines}\n\n"
        f"Functions to call (new version):\n{functions}\n\n"
        f"Diff (old to new):\n{ctx.diff[:MAX_DIFF_CHARS]}"
    )


class Characterizer:
    def __init__(
        self,
        llm: LLMClient,
        runner: CommandRunner,
        *,
        max_calls: int = MAX_CALLS,
        timeout_s: int = 60,
    ) -> None:
        self.llm = llm
        self.runner = runner
        self.max_calls = max_calls
        self.timeout_s = timeout_s

    def run(
        self,
        ctx: AuditContext,
        claims: list[Claim],
        ranges: dict[str, list[tuple[int, int]]],
    ) -> AgentResult:
        result = AgentResult()
        relevant = [
            claim
            for claim in claims
            if claim.kind in (ClaimKind.NO_BEHAVIOR_CHANGE, ClaimKind.FIXES)
        ]
        if not relevant:
            return result

        targets = select_targets(ctx.base_dir, ctx.head_dir, ranges)
        if not targets:
            result.findings.append(
                self._finding(
                    "Differential check skipped: no changed top-level Python function found",
                    Severity.INFO,
                )
            )
            return result

        try:
            calls = self._generate(ctx, relevant, targets)
        except LLMError as exc:
            result.findings.append(
                self._finding(
                    "Differential check skipped: input generation failed",
                    Severity.LOW,
                    str(exc)[:500],
                )
            )
            return result
        if not calls:
            result.findings.append(
                self._finding("Differential check skipped: no usable inputs", Severity.LOW)
            )
            return result

        self._write(ctx, calls)
        try:
            base_idx, base_rec = ctx.evidence.run(
                self.runner, ctx.base_dir, ARGV, timeout_s=self.timeout_s
            )
            head_idx, head_rec = ctx.evidence.run(
                self.runner, ctx.head_dir, ARGV, timeout_s=self.timeout_s
            )
            again_idx, again_rec = ctx.evidence.run(
                self.runner, ctx.head_dir, ARGV, timeout_s=self.timeout_s
            )
        finally:
            self._cleanup(ctx)

        base_res = parse_results(base_rec.stdout)
        head_res = parse_results(head_rec.stdout)
        again_res = parse_results(again_rec.stdout)
        records = (base_rec, head_rec, again_rec)
        if not (base_res and head_res and again_res) or any(
            is_infra_failure(record) for record in records
        ):
            detail = (head_rec.stderr or base_rec.stderr)[-500:]
            result.findings.append(
                Finding(
                    source="characterize",
                    title="Differential check could not run",
                    detail=detail,
                    severity=Severity.LOW,
                    command_indexes=[base_idx, head_idx, again_idx],
                )
            )
            return result

        comparable = [
            i
            for i in range(len(calls))
            if i in base_res
            and i in head_res
            and i in again_res
            and _signature(head_res[i]) == _signature(again_res[i])
        ]
        if comparable and all(head_res[i].get("exc") in IMPORT_ERRORS for i in comparable):
            result.findings.append(
                Finding(
                    source="characterize",
                    title="Differential check could not import the changed modules",
                    severity=Severity.LOW,
                    command_indexes=[base_idx, head_idx],
                )
            )
            return result

        differing = [i for i in comparable if _signature(base_res[i]) != _signature(head_res[i])]
        result.findings.append(
            Finding(
                source="characterize",
                title=(
                    f"Differential check: {len(comparable)} input(s) compared, "
                    f"{len(differing)} differ"
                ),
                severity=Severity.INFO,
                command_indexes=[base_idx, head_idx],
            )
        )

        for claim in relevant:
            if claim.kind is ClaimKind.NO_BEHAVIOR_CHANGE and differing:
                examples = "; ".join(
                    f"{_call_text(calls[i])} {_label(base_res[i])} on base but "
                    f"{_label(head_res[i])} on head"
                    for i in differing[:3]
                )
                self._refute(result, claim, f"Behavior differs: {examples}", [base_idx, head_idx])
            elif claim.kind is ClaimKind.FIXES:
                targeted = [i for i in comparable if calls[i].claim == claim.id]
                if not targeted or any(i in differing for i in targeted):
                    continue
                failing = [i for i in targeted if not head_res[i].get("ok")]
                if failing:
                    examples = "; ".join(
                        f"{_call_text(calls[i])} {_label(head_res[i])} on both versions"
                        for i in failing[:3]
                    )
                    self._refute(
                        result,
                        claim,
                        f"The input described by the claim still fails: {examples}",
                        [base_idx, head_idx],
                    )
        return result

    def _generate(
        self, ctx: AuditContext, claims: list[Claim], targets: list[Target]
    ) -> list[Call]:
        system = SYSTEM.replace("{n}", str(self.max_calls))
        data = complete_json(self.llm, system, _prompt(ctx, claims, targets))
        return parse_calls(data, targets, claims, self.max_calls)

    def _write(self, ctx: AuditContext, calls: list[Call]) -> None:
        payload = json.dumps(
            [
                {"module": c.module, "function": c.function, "args": c.args, "kwargs": c.kwargs}
                for c in calls
            ]
        )
        for root in (ctx.base_dir, ctx.head_dir):
            directory = root / CHAR_DIR
            directory.mkdir(exist_ok=True)
            (directory / "__init__.py").write_text("", encoding="utf-8")
            (directory / "driver.py").write_text(DRIVER, encoding="utf-8")
            (directory / "calls.json").write_text(payload, encoding="utf-8")

    def _cleanup(self, ctx: AuditContext) -> None:
        for root in (ctx.base_dir, ctx.head_dir):
            shutil.rmtree(root / CHAR_DIR, ignore_errors=True)

    @staticmethod
    def _finding(title: str, severity: Severity, detail: str = "") -> Finding:
        return Finding(source="characterize", title=title, detail=detail, severity=severity)

    @staticmethod
    def _refute(result: AgentResult, claim: Claim, explanation: str, indexes: list[int]) -> None:
        result.claim_results.append(
            ClaimResult(
                claim_id=claim.id,
                status=ClaimStatus.REFUTED,
                explanation=explanation[:1000],
                command_indexes=indexes,
            )
        )
        result.findings.append(
            Finding(
                source="characterize",
                title=f"Claim refuted: {claim.text}",
                detail=explanation[:1000],
                severity=Severity.HIGH,
                command_indexes=indexes,
            )
        )


def merge_characterization(
    audit: AgentResult, characterization: AgentResult, claims: list[Claim]
) -> None:
    by_id = {claim.id: claim for claim in claims}
    for refuted in characterization.claim_results:
        claim = by_id.get(refuted.claim_id)
        if claim is None:
            continue
        prior = [r for r in audit.claim_results if r.claim_id == refuted.claim_id]
        if any(r.status is ClaimStatus.REFUTED for r in prior):
            continue
        indexes = sorted({*refuted.command_indexes, *(i for r in prior for i in r.command_indexes)})
        audit.claim_results = [r for r in audit.claim_results if r.claim_id != refuted.claim_id]
        audit.claim_results.append(refuted.model_copy(update={"command_indexes": indexes}))
        stale = f"Claim not verified: {claim.text}"
        audit.findings = [f for f in audit.findings if f.title != stale]

    titles = {finding.title for finding in audit.findings}
    for finding in characterization.findings:
        if finding.title not in titles:
            audit.findings.append(finding)
            titles.add(finding.title)
